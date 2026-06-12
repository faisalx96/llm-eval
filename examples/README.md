# qym examples

Small, runnable examples for the qym SDK. Files marked *no keys* run
entirely offline against the local CSV dataset in `datasets/qa.csv`.

| Example | Needs | Shows |
| --- | --- | --- |
| `quickstart.ipynb` | no keys | End-to-end first evaluation (task, CSV dataset, metrics, optional platform streaming) |
| `csv_dataset_eval.py` | no keys | `CsvDataset` column mapping + custom metric |
| `example.py` | no keys | Metrics showcase: built-in registry, custom float/dict metrics, result stats |
| `multi_model.py` | no keys | `Evaluator.run_parallel` with two tasks side by side |
| `scale_example.py` | no keys | A (tasks x models) matrix with `max_parallel_runs` |
| `rag_eval_judges.py` | LLM API key | Built-in LLM judges (`faithfulness_llm`, `correctness_llm`) + `create_judge` |
| `vector_rag_chroma.py` | LLM API key + `pip install chromadb langchain-core langchain-chroma` | Chroma/LangChain retrieval tracing |
| `text2sql/` | qym platform + LLM API key | Mini-project: upload a platform dataset, then evaluate against it |

Set `QYM_API_KEY` (and `QYM_BASE_URL`, default `http://localhost:8000`) to
stream any run live to the qym platform; without it, runs stay local.

Examples that need missing credentials or optional packages print a clear
`[skip]` message and exit instead of crashing.
