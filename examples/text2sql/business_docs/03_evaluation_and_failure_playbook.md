# Text-to-SQL Evaluation and Failure Playbook

## Evaluation objective

The analyzer should determine whether generated SQL is a faithful implementation of the natural-language request in the supplied SQL context. It should explain failure patterns in business terms, identify the responsible layer, and recommend changes that can improve future runs.

For every failed or suspicious item, inspect the question, SQL context, expected SQL, generated SQL, metric scores, metric metadata, and trace evidence together. Do not diagnose an item from the aggregate score alone.

## Signals available in this example

### `valid_sql`

This metric strips a surrounding Markdown code block and parses the output with `sqlglot`. It checks syntax, not schema validity or business correctness. A score of 1 means the text is parseable; it does not prove that tables and columns exist or that the statement answers the question.

If `sqlglot` is unavailable, the fallback only recognizes text containing both `SELECT` and `FROM`. In that mode, valid DML, DDL, and some valid `SELECT` forms can receive false failures.

### `execution_accuracy`

This metric builds an in-memory SQLite database by splitting and executing the supplied SQL context, then executes the expected and generated statements and compares their fetched rows as sets.

Treat this as useful execution evidence, not conclusive semantic proof, because:

- setup-statement errors are silently ignored;
- converting results to sets ignores row order and duplicate counts;
- expected and generated statements run sequentially on the same database;
- successful `INSERT`, `UPDATE`, `DELETE`, and many DDL statements return no rows, so different operations may appear equivalent;
- the expected mutation can change state before the generated mutation runs; and
- an identical `CREATE TABLE` or `CREATE VIEW` can fail on its second execution because the object already exists.

These limitations are especially important for the 20 data-manipulation and data-definition items. A passing execution score on those items may be a false positive, while a correct DDL statement may receive a false failure.

### `relevance`

Use relevance as a semantic signal that the output addresses the request. It can identify topical or intent mismatches, but it should be checked against the concrete schema and expected SQL.

### `toxicity`

Toxicity is a general safety signal. It is not a SQL-correctness measure and should not outweigh direct evidence about syntax, execution, schema grounding, or business semantics.

## Failure taxonomy

Assign the most specific primary cause and mention meaningful secondary causes:

- **Instruction or format failure:** prose, Markdown, multiple statements, empty output, or truncated SQL.
- **Syntax or dialect failure:** malformed SQL or syntax unsupported by SQLite.
- **Schema-grounding failure:** invented or misspelled table or column, wrong alias, or invalid relationship.
- **Operation-type failure:** retrieval generated for a mutation request, mutation generated for analytics, or wrong DML/DDL verb.
- **Join failure:** missing join, wrong key, extra table, fan-out, or incorrect join type.
- **Predicate failure:** omitted, extra, or incorrect filter; wrong literal; unsafe mutation scope.
- **Boundary failure:** incorrect date, numeric, inclusion, exclusion, or range interpretation.
- **Aggregation failure:** wrong function, grouping level, `HAVING` logic, distinctness, or window partition.
- **Projection failure:** missing, extra, or incorrectly derived output columns.
- **Ordering or limit failure:** wrong rank direction, sort key, tie behavior, or row limit.
- **Expected-answer or dataset issue:** the reference SQL does not fully match the request, the context is insufficient, or an item is internally inconsistent.
- **Metric limitation:** a score is misleading because of parser fallback, SQLite incompatibility, result-set normalization, shared mutable state, or ignored setup errors.
- **Infrastructure failure:** provider, authentication, timeout, rate-limit, serialization, or tracing problem prevented a usable output.

## Root-cause decision sequence

1. Confirm that the task received the intended question and full SQL context.
2. Check whether a usable SQL-only response was returned.
3. Check parsing and SQLite execution errors.
4. Compare operation type and schema references.
5. Compare business semantics: predicates, joins, calculations, grouping, output shape, ordering, and limits.
6. Test whether the expected SQL itself matches the request.
7. Determine whether metric implementation details explain the observed score.
8. Use trace evidence to separate prompt/model behavior from provider or infrastructure failures.

## Reporting standard

An analysis should state what failed, why it matters to the business request, the evidence supporting the diagnosis, and the smallest durable fix. Separate recommendations into task-prompt changes, dataset or expected-answer corrections, metric changes, and infrastructure fixes. Avoid claiming that a model is broadly weak when the evidence supports only a specific pattern or a small number of examples.

When aggregating results, segment at least by operation type and SQL complexity. Overall averages can hide high-risk failures in mutations, joins, subqueries, window functions, and DDL.
