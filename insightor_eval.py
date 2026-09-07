# Standard library imports
import json
import os
import re
import random
import string
import threading
import time
import traceback
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Literal, Optional

# Third-party imports - Data science and ML
import pandas as pd
from openai import OpenAI
from pydantic import BaseModel, Field

# Third-party imports - API and web
import requests
import urllib3
from urllib3.exceptions import InsecureRequestWarning

urllib3.disable_warnings(InsecureRequestWarning)

# Third-party imports - Specialized tools
import dataikuapi
from dotenv import load_dotenv
from qym import Evaluator

load_dotenv()

_RUNTIME_OVERRIDES: Dict[str, Optional[str]] = {}


def configure_runtime(**kwargs: Optional[str]) -> None:
    for key, value in kwargs.items():
        if value is not None:
            _RUNTIME_OVERRIDES[key] = str(value)


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    value = _RUNTIME_OVERRIDES.get(name)
    if value not in (None, ""):
        return value
    return os.getenv(name, default)


def _unwrap_insightor_output(output: Any) -> Any:
    """Unwrap qym's task-output envelope for Insightor metrics."""
    if (
        isinstance(output, dict)
        and set(output) == {"output", "metadata"}
        and isinstance(output.get("output"), dict)
    ):
        return output["output"]
    return output


# =============================================================================
# PROMPT GENERATION FOR LLM EVALUATION
# =============================================================================


def get_prompts(output, expected, input_data):
    """
    Generate system and user prompts for LLM-based result evaluation.

    Args:
        output: Model-generated result
        expected: Expected/golden result
        input_data: Original input/question

    Returns:
        tuple: (system_prompt, user_prompt)
    """
    extra = "IMPORTANT: column names or placements differences DOES NOT affect the correctness. Only the actual values do."

    system_prompt = f"""You are an expert data evaluator. You will receive two result tables:
1. The correct result table (gold)
2. The model-generated result table (LLM)
Your task is to judge if the LLM result is acceptable based on the following criteria:

**VALUE-LEVEL COMPARISON RULES**
- Numbers are considered equal if they are within ±2%.
- Dates are considered equal if the format differs (e.g., '2025-01-01', '01-01-2025', or with time components).
- Strings must match exactly (case-sensitive).
- If two values are in different languages, they are considered equal IF they have the same meaning (e.g., "الكويت" and "Kuwait").
- If two values have different strings or different types but represent the **SAME** meaning, then they should be equal.
- If the meaning of the model-generated result matches the gold answer logically, even if formatting or column structure is different, consider it correct.
- If one value is a percentage out of 100 and the other is out of 1, then they are correct (e.g., 67 and 0.67).
- VERY IMPORTANT: if gold OR llm are empty (i.e. []) then it is automatically incorrect (return 0).

**COLUMN-LEVEL COMPARISON RULES**
- Column order does NOT matter.
- Extra columns in the LLM result ARE ALLOWED as long as every gold column is present.
- Missing any gold column = Incorrect.
{extra}

**ROW-LEVEL COMPARISON RULES**
- Row orders do NOT matter unless the question explicitly asks for the ranking or top n.
- Extra rows in the LLM result ARE ALLOWED as long as every gold row is present.
- Missing any gold row = Incorrect.

**IMPORTANT EXCEPTION**
When a column in the gold result is missing in the LLM result AND it does not affect the credibility of the answer OR not asked in the question, then consider it correct.
Examples include:
- Question asking for a specific value, and the LLM result provides that value.
- Gold result contains information not required by the question.
**HOWEVER**, if a question does not ask for a certain value and yet both answers provide it AND they differ according to the rules above, then it is NOT correct.

**EXAMPLES OF EXCEPTIONS**
Example 1:
  - Question: ما هي اقل منطقة فيها عدد سيارات؟
  - Gold result: [(منطقة الجنوب ,1000)]
  - LLM result: [(منطقة الجنوب)]
  - Reasoning: Question asked for the region name and not the counts, thus LLM result is correct.
Example 2:
  - Question: كم عدد المدرسين في جامعة الإمام محمد بن سعود الإسلامية
  - Gold result: [(40جامعة الإمام محمد بن سعود الإسلامية ,0)]
  - LLM result: [(400)]
  - Reasoning: Missing the university name is allowed since the question already mentions it and expecting the count, thus LLM result is correct.
Example 3:
  - Question: ما هي اكبر مدينة فيها سكان؟
  - Gold result: [(الرياض ,8000)]
  - LLM result: [(الرياض, 7000)]
  - Reasoning: Question did infact only ask for the city name, however since it is clear that the numbers are not matched, thus LLM result is wrong.

**RESPONSE FORMAT**
Respond in this exact JSON format on one line:
- If correct: {{"correctness": 1, "reasoning": "brief reason for correctness"}}
- If incorrect: {{"correctness": 0, "reasoning": "brief reason for incorrectness"}}
Only return one line in valid JSON. No extra text, no explanations outside the JSON."""

    user_prompt = (
        f"Question: {input_data}\n"
        f"Golden Answer: {expected}\n"
        f"Generated Answer: {output}\n"
    )
    return system_prompt, user_prompt


# =============================================================================
# DATA MODELS FOR LLM RESPONSE VALIDATION
# =============================================================================


class ResultJudgeOutput(BaseModel):
    """Pydantic model for validating LLM evaluation responses."""

    correctness: Literal[0, 1] = Field(
        ...,
        description="Binary flag – 1 if the answer is correct, 0 otherwise.",
    )
    reasoning: str = Field(
        ...,
        min_length=1,
        description="Human‑readable explanation of why the answer is (in)correct.",
    )


# =============================================================================
# RAG CONTEXT INFLUENCE JUDGE
# =============================================================================


class RAGContextJudgeOutput(BaseModel):
    """Pydantic model for validating RAG context judge responses."""

    followed_context: float = Field(
        ...,
        description="Score between 0 and 1, whether the provided context was used correctly to construct the query, if applicable.",
    )
    missed_context: List[str] = Field(
        ...,
        description="List of relevant context items that were not used by the agent.",
    )
    tables_from_context: List[str] = Field(
        ...,
        description="List all table names (or database/table identifiers) mentioned in the RAG context. Extract verbatim table names as they appear. If none, use [].",
    )
    context_section: List[
        Literal[
            "Tables Context",
            "Definitions Context",
            "Similar Queries Context",
            "no_influence",
        ]
    ] = Field(
        ...,
        description="Which top-level section of the RAG context influenced the agent's query.",
    )
    context_influences: Dict[str, List[str]] = Field(
        ...,
        description="Per top-level section, list verbatim text that influenced the agent's query. If no influence, use 'no_influence': [\"no influence\"].",
    )
    ground_truth_mismatch: bool = Field(
        ...,
        description="Whether the ground truth query contradicts instructions in the RAG context or includes steps not covered by the context.",
    )
    ground_truth_difference: str = Field(
        ...,
        description="When ground_truth_mismatch is true, explain the clear and explicit instructions that were violated, or assumptions the context did not cover.",
    )
    context_ambiguity: str = Field(
        ...,
        description="State any ambiguity in the context that led to the agent's query differing from the ground truth, or 'none' if none.",
    )
    reasoning: str = Field(
        ...,
        min_length=1,
        description="Brief reasoning for your assessment.",
    )


# =============================================================================
# DATA PROCESSING AND NORMALIZATION FUNCTIONS
# =============================================================================


def norm(v: Any) -> Any:
    """
    Canonicalize value for comparison (strip strings, unify NULL / NaN).

    Args:
        v: Value to normalize

    Returns:
        Normalized value suitable for comparison
    """
    if v is None:
        return None
    if isinstance(v, (float, Decimal, int)):
        return round(float(v), 2)
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, (pd.Timestamp, datetime)):
        return v.isoformat()
    return v


# =============================================================================
# DATABASE QUERY EXECUTION
# =============================================================================


def run_impala_query(query, timeout_time=120, limit=100):
    """
    Execute Impala SQL query and return results as DataFrame.

    Args:
        query: SQL query to execute
        timeout_time: Query timeout in seconds (default: 120)
        limit: Maximum number of rows to return (default: 100)

    Returns:
        pandas.DataFrame: Query results or empty DataFrame on error
    """
    try:
        # Establish connection to Dataiku Impala server
        dataiku_url = os.getenv("DATAIKU_URL", "https://dataiku.estishraf.gov.sa")
        dataiku_api_key = os.getenv("DATAIKU_API_KEY")
        if not dataiku_api_key:
            raise ValueError("DATAIKU_API_KEY is required")
        dataiku_client = dataikuapi.DSSClient(dataiku_url, dataiku_api_key)
        result = dataiku_client.sql_query(
            pre_queries=[f"set exec_time_limit_s={timeout_time}"],
            query=query,
            database="dataiku",
            type="impala",
        )

        # Extract schema and convert to DataFrame
        schema = [x["name"] for x in result.get_schema()]
        df = pd.DataFrame(list(result.iter_rows()), columns=schema)
        return df
    except Exception as e:
        # Return empty DataFrame on any error
        return pd.DataFrame()


def get_results(query: str) -> dict:
    """
    Execute SQL query and return normalized results.

    Args:
        query: SQL query string (may contain placeholders)

    Returns:
        dict: Dictionary with 'columns' and 'rows' keys
    """
    # Handle empty queries
    if query == "" or query is None:
        return {"columns": [], "rows": []}

    # Replace placeholder with current date
    CURRENT_DATE = "2025-06-17"
    df = run_impala_query(query.format(CURRENT_DATE=CURRENT_DATE))
    cols = df.columns.tolist()  # Get columns as a list of strings
    # Normalize all values for consistent comparison
    rows = [tuple(norm(v) for v in row) for row in df.values.tolist()]
    return {"columns": cols, "rows": rows}


# =============================================================================
# EXACT MATCH RESULT EVALUATION
# =============================================================================
class ExecutionAccuracy:
    def __init__(self):
        self.NUM_EPS = 0.0000001
        self.PERCENT_DIFF_THRESHOLD = 2

    def compare_rows(self, ref_row, gen_row):
        found = 0
        for ref_value in ref_row:
            for gen_value in gen_row:
                if isinstance(ref_value, (float, Decimal, int)) and isinstance(
                    gen_value, (float, Decimal, int)
                ):
                    # Compare numerical values within the tolerance
                    percent_diff = (
                        abs((ref_value - gen_value) / (ref_value + self.NUM_EPS)) * 100
                    )
                    if percent_diff <= self.PERCENT_DIFF_THRESHOLD:
                        found += 1
                        break
                    else:
                        continue
                else:
                    if ref_value == gen_value:
                        found += 1
                        break
                    else:
                        continue

        if found != len(ref_row):
            return False
        else:
            return True

    def compare_rows_perc(self, ref_row, gen_row):
        found = 0
        for ref_value in ref_row:
            for gen_value in gen_row:
                if isinstance(ref_value, (float, Decimal, int)) and isinstance(
                    gen_value, (float, Decimal, int)
                ):
                    # Compare numerical values within the tolerance
                    percent_diff = (
                        abs(
                            (float(ref_value) - float(gen_value))
                            / (float(ref_value) + self.NUM_EPS)
                        )
                        * 100
                    )
                    if percent_diff <= self.PERCENT_DIFF_THRESHOLD:
                        found += 1
                        break
                    else:
                        continue
                else:
                    if ref_value == gen_value:
                        found += 1
                        break
                    else:
                        continue

        perc = round(100 * found / len(ref_row))
        return perc

    def compare_results_perc(self, reference_data, generated_data):
        """Compare the results of the reference and generated queries and return percentage match."""
        row_score = 0
        cell_score = 0
        for ref_row in reference_data:
            comps = []
            for gen_row in generated_data:
                score = self.compare_rows_perc(ref_row, gen_row)
                comps.append(score)
                if score == 100:
                    row_score += 100
                    break

            cell_score += max(comps)

        cell_perc = round(cell_score / len(reference_data))
        row_perc = round(row_score / len(reference_data))

        return row_perc, cell_perc

    def evaluate(self, reference_rows, generated_rows):
        if len(generated_rows) > 0:
            EX_row, EX_cell = self.compare_results_perc(reference_rows, generated_rows)
        else:
            EX_row, EX_cell = (0, 0)

        return EX_row, EX_cell


def exact_match(output, expected, input_data=None):
    try:
        execution_accuracy = ExecutionAccuracy()

        _, EX_cell = execution_accuracy.evaluate(output, expected)
        error = None
    except Exception as e:
        exc_type = f"{type(e).__module__}.{type(e).__name__}"
        exc_value = str(e)
        exc_traceback = traceback.format_exc()
        error = json.dumps(
            {
                "exc_type": exc_type,
                "exc_value": exc_value,
                "exc_traceback": exc_traceback,
            },
            ensure_ascii=False,
        )
        EX_cell = 0

    # print("exact_match output", EX_cell >= 95)
    return {
        "score": EX_cell >= 95,
        "metadata": {"cell_f1": EX_cell, "error": error},
    }


# =============================================================================
# SQL PARSING HELPER FUNCTIONS
# =============================================================================


def extract_tables(sql: str) -> set:
    """
    Extract table names from SQL query using SQLGlot, excluding CTE aliases.

    Args:
        sql: SQL query string

    Returns:
        Set of lowercase table names (without schema prefix)
    """
    tables = set()

    if not sql or not sql.strip():
        return tables

    try:
        parsed = sqlglot.parse_one(sql, dialect="hive")

        # Collect CTE aliases first
        cte_names = set()
        for node in parsed.walk():
            if isinstance(node, exp.CTE):
                cte_names.add(node.alias)

        # Walk through all Table nodes, excluding CTE aliases
        for node in parsed.walk():
            if isinstance(node, exp.Table):
                table_name = node.name.lower()
                if table_name and table_name not in cte_names:
                    tables.add(table_name)
    except Exception as e:
        print(f"Error parsing SQL for tables: {e}")

    return list(tables)


# =============================================================================
# LLM-BASED RESULT EVALUATION
# =============================================================================


def extract_json(text: str) -> Optional[dict]:
    """
    Extracts a JSON object from text that may contain thinking tags or other surrounding content.
    Uses a brace-depth counter to correctly handle nested braces.
    """
    text = text.strip()
    if not text:
        return None

    brace_depth = 0
    start = None
    for i, ch in enumerate(text):
        if ch == "{":
            if brace_depth == 0:
                start = i
            brace_depth += 1
        elif ch == "}":
            brace_depth -= 1
            if brace_depth == 0 and start is not None:
                candidate = text[start : i + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    start = None
    return None


def llm_judge_metric(output, expected, input_data):
    """
    Use LLM to evaluate if generated result matches expected result.

    Args:
        output: Generated result to evaluate
        expected: Expected/correct result
        input_data: Original input/question

    Returns:
        dict: Evaluation result with score and reasoning
    """

    try:
        # Generate evaluation prompts
        system_prompt, user_prompt = get_prompts(output, expected, input_data)
        # Request LLM evaluation with structured output guidance
        llm_client = OpenAI(
            api_key=os.getenv("OPENAI_API_KEY"), base_url=os.getenv("OPENAI_BASE_URL")
        )
        response = llm_client.chat.completions.create(
            model="openai/gpt-oss-120b",
            temperature=0,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            extra_body={"guided_json": ResultJudgeOutput.model_json_schema()},
        )

        # Parse LLM response
        content = response.choices[0].message.content
        try:
            # Try to parse as JSON
            parsed = json.loads(content)
            correctness = parsed.get("correctness", 0)
            reasoning = parsed.get("reasoning", content)
        except json.JSONDecodeError as e:
            parsed = extract_json(content)
            if parsed:
                correctness = parsed.get("correctness", 0)
                reasoning = parsed.get("reasoning", content)
            else:
                correctness = None
                reasoning = f"Could not decode: {content}"

    except Exception as e:
        # Handle any evaluation errors
        correctness = 0
        reasoning = f"Error: {str(e)}"
        print(reasoning)

    return {"score": correctness, "metadata": {"reasoning": reasoning}}


def _format_value(key: str, value: Any) -> List[str]:
    """Format a single field value for display."""
    lines = []

    if isinstance(value, bool):
        lines.append(f"  {value}")
    elif isinstance(value, list):
        if not value:
            lines.append("  (none)")
        for item in value:
            lines.append(f"  - {item}")
    elif isinstance(value, dict):
        if not value:
            lines.append("  (none)")
        for section, items in value.items():
            lines.append(f"  {section}:")
            if isinstance(items, list):
                for item in items:
                    lines.append(f"    - {item}")
            else:
                lines.append(f"    {items}")
    else:
        clean_text = str(value).replace("\\n", "\n").strip()
        for line in clean_text.split("\n"):
            if line:
                lines.append(f"  {line}")

    return lines


def _section_label(key: str) -> str:
    """Pretty title for a metadata key."""
    labels = {
        "score": "Score",
        "generated_sql": "Generated SQL",
        "table_recall": "Table Recall",
        "retrieved_tables": "Retrieved Tables (from Context)",
        "groundtruth_tables": "Ground Truth Tables",
        "followed_context": "Followed Context",
        "missed_context": "Missed Context",
        "context_section": "Context Section",
        "context_influences": "Context Influences",
        "ground_truth_mismatch": "Ground Truth Mismatch",
        "ground_truth_difference": "Ground Truth Difference",
        "context_ambiguity": "Context Ambiguity",
        "reasoning": "Reasoning",
    }
    return labels.get(key, key.replace("_", " ").title())


def analysis_report(data):
    """
    Build a structured analysis report from context_judge metadata.

    Groups fields into logical sections with simple separators.
    """
    sep = "─" * 60

    def section(title):
        lines.append("")
        lines.append(title)
        lines.append(sep)

    lines = []

    # ── Score ──
    score = data.get("score")
    if score is not None:
        section("Score")
        lines.append("  Score: %s" % str(score))

    # ── Query ──
    sql = data.get("generated_sql")
    if sql:
        section("Query")
        sql_preview = str(sql)
        if len(sql_preview) > 60:
            sql_preview = sql_preview[:60] + "..."
        lines.append("  %s" % sql_preview)

    # ── Tables ──
    section("Tables")

    ctx_tables = data.get("context_tables")
    if ctx_tables:
        lines.append("  Context Tables:")
        for t in ctx_tables:
            lines.append("    • %s" % t)

    gt_tables = data.get("groundtruth_tables")
    if gt_tables:
        lines.append("  Ground Truth Tables:")
        for t in gt_tables:
            lines.append("    • %s" % t)

    if ctx_tables or gt_tables:
        lines.append("")

    all_gt_in_ctx = data.get("all_groundtruth_in_context")
    if all_gt_in_ctx is not None:
        status = (
            "✅ All GT tables in context"
            if all_gt_in_ctx
            else "❌ Some GT tables missing from context"
        )
        lines.append("  %s" % status)

    gen_tables = data.get("generated_tables")
    if gen_tables:
        lines.append("  Generated Tables:")
        for t in gen_tables:
            lines.append("    • %s" % t)

    table_recall = data.get("table_recall")
    recall = data.get("recall")
    recall_val = recall if recall is not None else table_recall
    if recall_val is not None:
        lines.append("  Table Recall: %.2f" % recall_val)

    # ── Context Analysis ──
    followed = data.get("followed_context")
    if followed is not None:
        section("Context Analysis")
        lines.append("  Followed Context: %.2f" % followed)

    ctx_sections = data.get("context_section")
    if ctx_sections:
        lines.append("  Influenced Sections: %s" % ", ".join(ctx_sections))

    missed = data.get("missed_context")
    if missed:
        lines.append("  Missed Context:")
        for m in missed:
            lines.append("    • %s" % m)

    ctx_influences = data.get("context_influences")
    if ctx_influences and isinstance(ctx_influences, dict):
        lines.append("  Context Influences:")
        for section_name, snippets in ctx_influences.items():
            lines.append("    %s:" % section_name)
            if isinstance(snippets, list):
                for s in snippets:
                    lines.append("      – %s" % s)
            else:
                lines.append("      – %s" % snippets)

    # ── Ground Truth Alignment ──
    mismatch = data.get("ground_truth_mismatch")
    diff = data.get("ground_truth_difference")
    ambiguity = data.get("context_ambiguity")
    if (
        mismatch is not None
        or (diff and diff != "N/A")
        or (ambiguity and ambiguity != "none")
    ):
        section("Ground Truth Alignment")
        if mismatch is not None:
            lines.append("  Mismatch: %s" % mismatch)
        if diff and diff != "N/A":
            lines.append("  Difference: %s" % diff)
        if ambiguity and ambiguity != "none":
            lines.append("  Ambiguity: %s" % ambiguity)

    # ── Reasoning ──
    reasoning = data.get("reasoning")
    if reasoning:
        section("Reasoning")
        for rline in str(reasoning).split("\n"):
            if rline.strip():
                lines.append("  %s" % rline.strip())

    return "\n".join(lines)


def context_judge(output, expected, input_data) -> str:
    """
    Use LLM to judge what influence the RAG context had on the agent's query
    compared to the ground truth query.

    Args:
        output: dict with keys 'sql' (generated query), 'context' (RAG context), 'agent_response'
        expected: ground truth query string
        input_data: original question

    Returns:
        dict with context_differed, context_influences, and reasoning
    """
    output = _unwrap_insightor_output(output)
    generated_sql = output.get("sql", "")
    context = output.get("context", "")

    # Extract tables from context (table names under "Tables Context" section)
    tables_match = re.search(r"# Tables Context\n(.*?)(?=\n# |\Z)", context, re.DOTALL)
    if tables_match:
        tables_section = tables_match.group(1)
        retrieved_tables = re.findall(r"^###\s+([\w_]+):", tables_section, re.MULTILINE)
        retrieved_tables = (
            [t.strip() for t in retrieved_tables] if retrieved_tables else []
        )
    else:
        retrieved_tables = []

    # Extract tables from ground truth query using sqlglot
    groundtruth_tables = extract_tables(expected)

    # Table recall: does the context contain the tables needed for the ground truth query?
    gold_set = set(groundtruth_tables)
    context_set = set(retrieved_tables)
    table_recall = len(context_set & gold_set) / len(gold_set) if gold_set else 0.0

    if not context:
        return {
            "score": None,
            "metadata": {
                "generated_sql": generated_sql,
                "table_recall": table_recall,
                "retrieved_tables": retrieved_tables,
                "groundtruth_tables": groundtruth_tables,
                "reasoning": "No RAG context available for this run.",
            },
        }

    system_prompt = """
You are an expert data evaluator analyzing how RAG context influenced an agent's SQL query.

You will receive:
1. A question from the user
2. The ground truth query (always treat this as correct — if context contradicts it, the context is wrong)
3. The agent's generated query
4. The RAG context injected into the agent

Respond in valid JSON with these exact keys:

- followed_context: float between 0 and 1. Score for whether the agent followed the context provided and did not miss instructions. Deduct if vital relevant context was not used.
- missed_context: array of strings. Each element describes a relevant context item that the agent did not use but should have. Do not include analysis regarding the ground truth query. If none, use []. If followed_context less than 1, then you MUST provide something.
- tables_from_context: array of strings. List all table names (or database/table identifiers) mentioned in the RAG context. Extract verbatim. If none, use [].
- context_section: array of strings. Which top-level section(s) of the context influenced the agent: "Tables Context", "Definitions Context", "Similar Queries Context", or "no_influence".
- context_influences: object mapping each influenced section to an array of verbatim text snippets that shaped the agent's query. If no influence, use {"no_influence": ["no influence"]}.
- ground_truth_mismatch: boolean. True if the ground truth query contradicts instructions in the context or includes steps not covered by the context.
- ground_truth_difference: string. When ground_truth_mismatch is true, explain the clear and explicit instructions that were violated, or assumptions the context did not cover. Otherwise, "N/A".
- context_ambiguity: string. State any ambiguity in the context that led to the agent's query differing from the ground truth, or "none" if none.
- reasoning: string. Brief reasoning for your assessment.

Example:
{"followed_context": 0.8, "missed_context": ["some missed detail"], "tables_from_context": ["table1", "table2"], "context_section": ["Tables Context"], "context_influences": {"Tables Context": ["verbatim text from context"]}, "ground_truth_mismatch": false, "ground_truth_difference": "N/A", "context_ambiguity": "none", "reasoning": "brief reasoning..."}

Only return valid JSON — no extra text.
"""

    user_prompt = (
        f"Question: {input_data}\n\n"
        f"Ground Truth Query: {expected}\n\n"
        f"Generated Query: {generated_sql}\n\n"
        f"RAG Context:\n{context}"
    )

    # Define how many times to try
    MAX_RETRIES = 3

    # --- inside your worker function ---
    for attempt in range(MAX_RETRIES):
        try:
            context_judge_api_key = os.getenv("CONTEXT_JUDGE_API_KEY") or os.getenv(
                "OPENAI_API_KEY"
            )
            if not context_judge_api_key:
                raise ValueError("CONTEXT_JUDGE_API_KEY or OPENAI_API_KEY is required")
            llm_client = OpenAI(
                api_key=context_judge_api_key,
                base_url=os.getenv(
                    "CONTEXT_JUDGE_BASE_URL", "https://aigateway.estishraf.gov.sa/v1"
                ),
            )
            response = llm_client.chat.completions.create(
                model="openai/gpt-oss-120b",  # "google/gemma-4-31B-it",
                temperature=0,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                extra_body={
                    "guided_json": RAGContextJudgeOutput.model_json_schema(),
                    "chat_template_kwargs": {"enable_thinking": True},
                },
            )
            content = response.choices[0].message.content

            try:
                parsed = json.loads(content)
            except json.JSONDecodeError:
                parsed = extract_json(content)

            # If parsing failed, we manually trigger the 'except' block to retry
            if parsed is None:
                raise ValueError("JSON parsing failed")

            # If we reached here, it succeeded! Return and exit the loop.
            return {
                "score": parsed.get("followed_context"),
                "metadata": {
                    "generated_sql": generated_sql,
                    "table_recall": table_recall,
                    "retrieved_tables": retrieved_tables,
                    "groundtruth_tables": groundtruth_tables,
                    "followed_context": parsed.get("followed_context"),
                    "missed_context": parsed.get("missed_context", []),
                    "context_section": parsed.get("context_section", []),
                    "context_influences": parsed.get("context_influences", {}),
                    "ground_truth_mismatch": parsed.get("ground_truth_mismatch"),
                    "ground_truth_difference": parsed.get(
                        "ground_truth_difference", "N/A"
                    ),
                    "context_ambiguity": parsed.get("context_ambiguity", "none"),
                    "reasoning": parsed.get("reasoning"),
                },
            }

        except Exception as e:
            print(f"Attempt {attempt + 1} failed: {e}")
            if attempt == MAX_RETRIES - 1:  # Last attempt failed
                return {
                    "score": None,
                    "metadata": {
                        "generated_sql": None,
                        "table_recall": table_recall,
                        "retrieved_tables": retrieved_tables,
                        "groundtruth_tables": groundtruth_tables,
                        "reasoning": f"Error after {MAX_RETRIES} tries: {str(e)}",
                    },
                }
            # Optional: wait 1 second before trying again
            import time

            time.sleep(1)


# =============================================================================
# MAIN ACCURACY METRIC FUNCTION
# =============================================================================


def accuracy(output, expected, input_data=None) -> dict:
    """
    Main accuracy metric that combines SQL execution and LLM evaluation.

    Args:
        output: Model output containing SQL query
        expected: Expected SQL query
        input_data: Original input/question (optional)

    Returns:
        dict: Accuracy score and detailed metadata
    """
    output = _unwrap_insightor_output(output)

    # Initialize result tracking variables
    llm_result = {}
    expected_result = {}
    score = False
    exact_match_result_score = False
    llm_judge_metric_result_score = False
    exact_match_cell_f1 = 0
    exact_match_error = ""
    llm_judge_reasoning = ""
    error = ""

    try:
        request_id = output.get("request_id", "")

        # Execute both SQL queries and get results
        step_start = time.time()
        llm_result = get_results(output["sql"])
        expected_result = get_results(expected)
        _log_timing(
            {
                "type": "metric_step",
                "metric": "accuracy",
                "step": "get_results",
                "duration_seconds": round(time.time() - step_start, 4),
                "request_id": request_id,
            }
        )

        # Evaluate results using Exact Match
        step_start = time.time()
        exact_match_result = exact_match(llm_result["rows"], expected_result["rows"])
        exact_match_result_score = exact_match_result["score"]
        _log_timing(
            {
                "type": "metric_step",
                "metric": "accuracy",
                "step": "exact_match",
                "duration_seconds": round(time.time() - step_start, 4),
                "request_id": request_id,
            }
        )

        # Evaluate results using LLM judge
        step_start = time.time()
        llm_judge_metric_result = llm_judge_metric(
            llm_result, expected_result, input_data
        )
        llm_judge_metric_result_score = llm_judge_metric_result["score"]
        _log_timing(
            {
                "type": "metric_step",
                "metric": "accuracy",
                "step": "llm_judge_metric",
                "duration_seconds": round(time.time() - step_start, 4),
                "request_id": request_id,
            }
        )

        # Set final score and reasoning
        score = exact_match_result_score | llm_judge_metric_result_score
        exact_match_cell_f1 = exact_match_result["metadata"]["cell_f1"]
        exact_match_error = exact_match_result["metadata"]["error"]
        llm_judge_reasoning = llm_judge_metric_result["metadata"]["reasoning"]

    except Exception as e:
        # Capture any errors during evaluation
        error = f"ERROR: {e}"

    # Compile comprehensive metadata
    metadata = {
        "llm_result": llm_result,
        "expected_result": expected_result,
        "exact_match_result_score": exact_match_result_score,
        "llm_judge_metric_result_score": llm_judge_metric_result_score,
        "exact_match_cell_f1": exact_match_cell_f1,
        "exact_match_error": exact_match_error,
        "llm_judge_reasoning": llm_judge_reasoning,
        "error": error,
    }

    return {
        "score": score,
        "metadata": metadata,
    }


# =============================================================================
# TIMING LOGGER
# =============================================================================

_timings_lock = threading.Lock()
_timings_file = os.path.join(os.path.dirname(__file__), "eval_timings.jsonl")


def _log_timing(entry: dict):
    """Append a timing entry to the timings file (thread-safe)."""
    with _timings_lock:
        os.makedirs(os.path.dirname(_timings_file), exist_ok=True)
        with open(_timings_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# =============================================================================
# INSIGHTOR API CLIENT
# =============================================================================

# Thread lock for safe concurrent file writes
response_file_lock = threading.Lock()
# Output file path for API responses (JSON Lines format)
API_RESPONSES_FILE = os.path.join(os.path.dirname(__file__), "api_responses.jsonl")
MAX_SSE_WARNINGS = 20


def _record_sse_warning(warnings: List[str], message: str) -> None:
    """Record a bounded parser warning without interrupting the stream."""
    if len(warnings) < MAX_SSE_WARNINGS:
        warnings.append(message)


def _parse_sse_data_line(raw_line: Any, warnings: List[str]) -> Optional[dict]:
    """Parse one SSE data line, returning None for control or malformed lines."""
    if isinstance(raw_line, bytes):
        try:
            line = raw_line.decode("utf-8")
        except UnicodeDecodeError:
            _record_sse_warning(warnings, "Ignored SSE line with invalid UTF-8")
            return None
    elif isinstance(raw_line, str):
        line = raw_line
    else:
        _record_sse_warning(
            warnings, f"Ignored SSE line with unexpected type {type(raw_line).__name__}"
        )
        return None

    # Accept both the canonical ``data:payload`` form and ``data: payload``.
    if not line.startswith("data:"):
        return None
    payload = line[5:].lstrip()
    if not payload or payload == "[DONE]":
        return None

    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, TypeError):
        _record_sse_warning(warnings, "Ignored SSE line with invalid JSON")
        return None
    if not isinstance(data, dict):
        _record_sse_warning(warnings, "Ignored SSE JSON payload that was not an object")
        return None
    return data


def _mapping_or_empty(
    value: Any, warnings: List[str], field_name: str
) -> Dict[str, Any]:
    """Return a mapping value or an empty mapping while recording schema drift."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    _record_sse_warning(
        warnings,
        f"Ignored non-object SSE field '{field_name}' ({type(value).__name__})",
    )
    return {}


def _nonempty_string(value: Any, warnings: List[str], field_name: str) -> Optional[str]:
    """Return a non-empty string, ignoring invalid values without raising."""
    if value is None or value == "":
        return None
    if isinstance(value, str):
        return value
    _record_sse_warning(
        warnings,
        f"Ignored non-string SSE field '{field_name}' ({type(value).__name__})",
    )
    return None


def _context_string(value: Any, warnings: List[str], field_name: str) -> Optional[str]:
    """Normalize textual or structured context without trusting its shape."""
    if value is None or value == "":
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    _record_sse_warning(
        warnings,
        f"Ignored unsupported SSE field '{field_name}' ({type(value).__name__})",
    )
    return None


def _auth_error_detail(response: requests.Response) -> str:
    """Return a bounded server error without exposing submitted credentials."""
    try:
        payload = response.json()
    except (TypeError, ValueError):
        payload = None

    if isinstance(payload, dict):
        for key in ("detail", "message", "error_description", "error"):
            value = payload.get(key)
            if value:
                if isinstance(value, (dict, list)):
                    return json.dumps(value, ensure_ascii=False)[:500]
                return str(value)[:500]

    text = str(getattr(response, "text", "") or "").strip()
    return text[:500] if text else "no error details returned"


def insightor_api(question: str) -> Dict[str, Any]:
    """
    Simplified Insightor API client that handles authentication and messaging.

    Args:
        question: The question or message to send

    Returns:
        Dictionary containing SQL query and Langfuse URL

    Raises:
        RuntimeError: If Insightor reports a failed internal task or the SSE
            stream finishes without producing SQL.
    """
    base_url = _env("INSIGHTOR_URL")
    access_token = None
    refresh_error: Optional[str] = None
    session = requests.Session()

    def _refresh_token() -> bool:
        """Refresh the access token using the refresh_token."""
        nonlocal access_token, refresh_error
        refresh_error = None
        try:
            response = requests.post(
                f"{base_url}/auth/token",
                json={"refresh_token": _env("REFRESH_TOKEN")},
                headers={"Content-Type": "application/json"},
                verify=False,
                timeout=30,
            )

            if response.status_code == 200:
                try:
                    data = response.json()
                except (TypeError, ValueError):
                    refresh_error = "HTTP 200 returned invalid JSON"
                    return False
                if not isinstance(data, dict):
                    refresh_error = (
                        f"HTTP 200 returned {type(data).__name__}, expected an object"
                    )
                    return False
                access_token = data.get("access_token")
                if isinstance(access_token, str) and access_token:
                    session.headers["Authorization"] = f"Bearer {access_token}"
                    return True
                refresh_error = "HTTP 200 response did not include access_token"
                return False
            refresh_error = (
                f"HTTP {response.status_code}: {_auth_error_detail(response)}"
            )
            return False
        except requests.RequestException as e:
            refresh_error = f"{type(e).__name__}: {e}"
            return False

    def _generate_id(prefix: str) -> str:
        """Generate a unique ID matching frontend format."""
        timestamp = int(time.time() * 1000)
        random_suffix = "".join(
            random.choices(string.ascii_lowercase + string.digits, k=7)
        )
        return f"{prefix}_{timestamp}_{random_suffix}"

    def _make_request(method: str, path: str, **kwargs) -> requests.Response:
        """Make HTTP request with automatic token refresh on 401."""
        # Ensure we have a token
        if not access_token and not _refresh_token():
            raise ValueError(
                f"Failed to obtain access token: {refresh_error or 'unknown error'}"
            )

        url = f"{base_url}{path}"
        response = session.request(method, url, **kwargs)

        # Handle 401 - attempt token refresh and retry
        if response.status_code == 401:
            if _refresh_token():
                response = session.request(method, url, **kwargs)
                if response.status_code == 401:
                    raise ValueError("Authentication failed after token refresh")
            else:
                raise ValueError(
                    f"Token refresh failed: {refresh_error or 'unknown error'}"
                )

        return response

    # Generate conversation and request IDs
    conversation_id = _generate_id("conv")
    request_id = _generate_id("req")

    # Log agent start
    _log_timing(
        {
            "type": "agent_start",
            "request_id": request_id,
            "question": question,
            "timestamp": datetime.utcnow().isoformat(),
        }
    )

    # Prepare payload
    payload = {
        "message": question,
        "conversation_id": conversation_id,
        "request_id": request_id,
    }

    # Make API request
    api_start = time.time()
    response = _make_request(
        "POST",
        "/change/api/vanna/v2/chat_sse",
        json=payload,
        stream=True,
        timeout=120,
        verify=False,
        headers={"Accept": "text/event-stream"},
    )
    response.raise_for_status()

    # Process streaming response and log each event
    start_time = time.time()
    streaming_events = []
    agent_response = ""
    generated_sql = ""
    langfuse_url = ""
    context = ""
    sse_warnings: List[str] = []

    for line in response.iter_lines():
        if not line:
            continue
        elapsed = time.time() - start_time
        data = _parse_sse_data_line(line, sse_warnings)
        if data is None:
            continue

        rich = _mapping_or_empty(data.get("rich"), sse_warnings, "rich")
        rich_type = _nonempty_string(rich.get("type"), sse_warnings, "rich.type") or ""
        rich_data = _mapping_or_empty(rich.get("data"), sse_warnings, "rich.data")

        # Extract key info for logging
        event_info = {"elapsed_seconds": round(elapsed, 2), "type": rich_type}

        # Add type-specific info
        if rich_type == "status_bar_update":
            event_info["message"] = rich_data.get("message", "")
            event_info["level"] = rich_data.get("level", "")
        elif rich_type == "task_tracker_update":
            task = _mapping_or_empty(rich_data.get("task"), sse_warnings, "task")
            event_info["task_id"] = rich_data.get("task_id", "")
            event_info["task_status"] = task.get("status", "")
            event_info["task_title"] = task.get("title", "")
            task_metadata = _mapping_or_empty(
                task.get("metadata"), sse_warnings, "task.metadata"
            )

            insightor_task_status = str(task.get("status", "")).strip().lower()
            if insightor_task_status in {"failed", "error"}:
                raw_error = (
                    task_metadata.get("error")
                    or task_metadata.get("message")
                    or task.get("error")
                    or task.get("message")
                    or rich_data.get("message")
                )
                if isinstance(raw_error, (dict, list)):
                    error_message = json.dumps(raw_error, ensure_ascii=False)
                else:
                    error_message = str(raw_error or "").strip()
                if not error_message:
                    task_id = (
                        task.get("id")
                        or rich_data.get("task_id")
                        or "unknown"
                    )
                    error_message = (
                        f"Insightor task '{task_id}' reported status "
                        f"'{insightor_task_status}'"
                    )
                raise RuntimeError(f"Insightor task failed: {error_message[:500]}")

            next_langfuse_url = _nonempty_string(
                task_metadata.get("langfuse_url"),
                sse_warnings,
                "task.metadata.langfuse_url",
            )
            if next_langfuse_url:
                langfuse_url = next_langfuse_url
                event_info["langfuse_url"] = langfuse_url

            if (
                task.get("id") == "rag_context_inject"
                and task.get("status") == "completed"
            ):
                next_context = _context_string(
                    task_metadata.get("context"),
                    sse_warnings,
                    "task.metadata.context",
                )
                if next_context:
                    context = next_context
                else:
                    _record_sse_warning(
                        sse_warnings,
                        "Completed rag_context_inject task did not include context",
                    )

        elif rich_type == "status_card":
            metadata = _mapping_or_empty(
                rich_data.get("metadata"), sse_warnings, "status_card.metadata"
            )
            next_sql = _nonempty_string(
                metadata.get("sql"), sse_warnings, "status_card.metadata.sql"
            )
            event_info["has_sql"] = bool(next_sql)
            event_info["has_result"] = "result" in metadata
            if next_sql:
                generated_sql = next_sql
        elif rich_type == "tool_call":
            tool_name = _nonempty_string(
                rich_data.get("name"), sse_warnings, "tool_call.name"
            )
            event_info["tool_name"] = tool_name or ""
            if tool_name == "run_sql":
                args = _mapping_or_empty(
                    rich_data.get("args"), sse_warnings, "tool_call.args"
                )
                next_sql = _nonempty_string(
                    args.get("sql"), sse_warnings, "tool_call.args.sql"
                )
                if next_sql:
                    generated_sql = next_sql
        elif rich_type == "tool_result":
            result_data = _mapping_or_empty(
                rich_data.get("result"), sse_warnings, "tool_result.result"
            )
            next_sql = _nonempty_string(
                result_data.get("sql"), sse_warnings, "tool_result.result.sql"
            )
            if next_sql:
                generated_sql = next_sql
                event_info["has_sql"] = True
        elif rich_type == "text":
            content = _nonempty_string(
                rich_data.get("content"), sse_warnings, "text.content"
            )
            event_info["text_preview"] = content[:100] if content else ""
            if content:
                agent_response = content

        streaming_events.append(event_info)

    if not generated_sql:
        raise RuntimeError("Insightor SSE stream ended without a SQL result")

    response_data = {
        "sql": generated_sql,
        "agent_response": agent_response,
        "context": context,
        "langfuse_url": langfuse_url,
    }
    if sse_warnings:
        response_data["sse_warnings"] = sse_warnings

    # Thread-safe write to JSON Lines file (raw response + streaming events)
    # with response_file_lock:
    #     os.makedirs(os.path.dirname(API_RESPONSES_FILE), exist_ok=True)
    #     log_entry = {
    #         "timestamp": datetime.utcnow().isoformat(),
    #         "request_id": request_id,
    #         "conversation_id": conversation_id,
    #         "question": question,
    #         "streaming_events": streaming_events
    #     }
    #     with open(API_RESPONSES_FILE, "a", encoding="utf-8") as f:
    #         f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

    api_end = time.time()
    _log_timing(
        {
            "type": "agent_end",
            "request_id": request_id,
            "duration_seconds": round(api_end - api_start, 4),
            "timestamp": datetime.utcnow().isoformat(),
        }
    )

    task_metadata = {
        "context": context,
        "external_trace_url": langfuse_url,
    }
    if sse_warnings:
        task_metadata["sse_warnings"] = list(sse_warnings)

    return {
        "output": response_data,
        "metadata": task_metadata,
    }


if __name__ == "__main__":
    # =============================================================================
    # EVALUATION SETUP AND EXECUTION
    # =============================================================================

    # Load evaluation dataset
    # from qym import CsvDataset
    # dataset = CsvDataset(
    #     path="/home/coder/insightor_poc/evaluation/evaluation_datasets/full_agent_evaluation_fixed_v4_no_jobs.csv",
    #     input_col="question",
    #     expected_col="query"
    # )

    results = Evaluator.run_parallel(
        runs=[
            {
                "name": f"{_env('AGENT_VERSION')}_{_env('IMAGE_VERSION')}_{_env('KB_VERSION')}",
                "task": insightor_api,
                "dataset": os.getenv("EVAL_DATASET"),
                "metrics": [accuracy],
                "model": os.getenv(
                    "MODEL"
                ),  # "Qwen/Qwen3-Coder-30B-React-V2-150S", #"Qwen/Qwen3.5-27B-SG", #google/gemma-4-31B-it_NT", #Qwen/Qwen3-Coder-480B", #"Qwen3-30B-LongContext", # "Qwen/Qwen3.5-397B", #"Qwen/Qwen3.5-27B", #"Qwen3-30B-LongContext", # Qwen/Qwen3-30B-A3B-Instruct-2507
                "config": {
                    "max_concurrency": 15,
                    "host": _env("INSIGHTOR_URL"),
                    "kb": _env("KB_VERSION"),
                    "timeout": 900,
                    "max_retries": 1,
                    "checkpoint_enabled": False,
                    "platform_url": os.getenv("QYM_BASE_URL"),
                    "platform_api_key": os.getenv("QYM_API_KEY"),
                },
            }
        ]
        * 1,
        auto_save=False,
        max_parallel_runs=1,  # Control how many runs execute at once (see below)
    )
