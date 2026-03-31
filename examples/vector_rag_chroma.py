"""
Minimal vector DB evaluation example using Chroma + qym.

This is designed to test tracing of:
- qym eval/task spans
- LangChain retriever spans
- direct chromadb calls
- Chroma-backed retrieval
- OpenAI-compatible chat completions

Install the optional dependencies first:

    pip install chromadb langchain-core langchain-chroma openai

Then run:

    python examples/vector_rag_chroma.py --mode langchain
    python examples/vector_rag_chroma.py --mode chromadb

Environment variables:
- OPENAI_API_KEY or OPENROUTER_API_KEY
- OPENAI_BASE_URL or OPENROUTER_BASE_URL (optional)
"""

import argparse
import csv
import hashlib
import os
import tempfile
from typing import List, Optional

import chromadb
from dotenv import load_dotenv
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from openai import AsyncOpenAI

from qym import Evaluator
from qym.core.dataset import CsvDataset

load_dotenv()


class SimpleHashEmbeddings(Embeddings):
    """Deterministic local embeddings to keep the example self-contained."""

    def __init__(self, dims: int = 16):
        self.dims = dims

    def _embed(self, text: str) -> List[float]:
        buckets = [0.0] * self.dims
        for token in text.lower().split():
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            idx = digest[0] % self.dims
            sign = 1.0 if digest[1] % 2 == 0 else -1.0
            buckets[idx] += sign
        norm = sum(v * v for v in buckets) ** 0.5 or 1.0
        return [v / norm for v in buckets]

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> List[float]:
        return self._embed(text)


def build_retriever():
    docs = [
        Document(
            page_content="Paris is the capital of France.",
            metadata={"title": "France", "source": "seed://countries/france"},
        ),
        Document(
            page_content="Tokyo is the capital of Japan.",
            metadata={"title": "Japan", "source": "seed://countries/japan"},
        ),
        Document(
            page_content="Riyadh is the capital of Saudi Arabia.",
            metadata={"title": "Saudi Arabia", "source": "seed://countries/saudi-arabia"},
        ),
        Document(
            page_content="Canberra is the capital of Australia.",
            metadata={"title": "Australia", "source": "seed://countries/australia"},
        ),
    ]
    vectorstore = Chroma.from_documents(
        documents=docs,
        embedding=SimpleHashEmbeddings(),
        collection_name="qym-chroma-example",
    )
    return vectorstore.as_retriever(search_kwargs={"k": 2})


def build_raw_chromadb_collection():
    client = chromadb.Client()
    try:
      client.delete_collection("qym-chroma-example-raw")
    except Exception:
      pass
    collection = client.create_collection("qym-chroma-example-raw")
    docs = [
        "Paris is the capital of France.",
        "Tokyo is the capital of Japan.",
        "Riyadh is the capital of Saudi Arabia.",
        "Canberra is the capital of Australia.",
    ]
    ids = [f"doc-{i}" for i in range(len(docs))]
    embeddings = SimpleHashEmbeddings().embed_documents(docs)
    metas = [
        {"title": "France", "source": "seed://countries/france"},
        {"title": "Japan", "source": "seed://countries/japan"},
        {"title": "Saudi Arabia", "source": "seed://countries/saudi-arabia"},
        {"title": "Australia", "source": "seed://countries/australia"},
    ]
    collection.add(ids=ids, documents=docs, embeddings=embeddings, metadatas=metas)
    return collection


def build_dataset_file() -> str:
    rows = [
        {"question": "What is the capital of France?", "expected": "Paris"},
        {"question": "What is the capital of Japan?", "expected": "Tokyo"},
        {"question": "What is the capital of Saudi Arabia?", "expected": "Riyadh"},
    ]
    fd, path = tempfile.mkstemp(prefix="qym_chroma_eval_", suffix=".csv")
    os.close(fd)
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["question", "expected"])
        writer.writeheader()
        writer.writerows(rows)
    return path


def build_client() -> AsyncOpenAI:
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("Set OPENAI_API_KEY or OPENROUTER_API_KEY before running this example.")
    base_url = os.getenv("OPENAI_BASE_URL") or os.getenv("OPENROUTER_BASE_URL")
    kwargs = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    return AsyncOpenAI(**kwargs)


RETRIEVER = build_retriever()
RAW_COLLECTION = build_raw_chromadb_collection()
CLIENT = build_client()


async def rag_with_chroma(question: str, model_name: Optional[str] = None) -> str:
    docs = RETRIEVER.invoke(question)
    context = "\n".join(doc.page_content for doc in docs)
    model = model_name or "openai/gpt-4o-mini"
    response = await CLIENT.chat.completions.create(
        model=model,
        temperature=0.0,
        messages=[
            {
                "role": "system",
                "content": "Answer with only the capital city name using the provided context.",
            },
            {
                "role": "user",
                "content": f"Context:\n{context}\n\nQuestion: {question}",
            },
        ],
    )
    return (response.choices[0].message.content or "").strip()


async def rag_with_raw_chromadb(question: str, model_name: Optional[str] = None) -> str:
    embedding = SimpleHashEmbeddings().embed_query(question)
    result = RAW_COLLECTION.query(
        query_embeddings=[embedding],
        n_results=2,
        include=["documents", "metadatas", "distances"],
    )
    docs = result.get("documents", [[]])[0]
    context = "\n".join(str(doc) for doc in docs if doc)
    model = model_name or "openai/gpt-4o-mini"
    response = await CLIENT.chat.completions.create(
        model=model,
        temperature=0.0,
        messages=[
            {
                "role": "system",
                "content": "Answer with only the capital city name using the provided context.",
            },
            {
                "role": "user",
                "content": f"Context:\n{context}\n\nQuestion: {question}",
            },
        ],
    )
    return (response.choices[0].message.content or "").strip()


def contains_expected(output: str, expected: str) -> float:
    return 1.0 if expected.lower() in (output or "").lower() else 0.0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["langchain", "chromadb"], default="langchain")
    args = parser.parse_args()

    csv_path = build_dataset_file()
    dataset = CsvDataset(csv_path, input_col="question", expected_col="expected")
    task = rag_with_chroma if args.mode == "langchain" else rag_with_raw_chromadb
    evaluator = Evaluator(
        task=task,
        dataset=dataset,
        metrics=[contains_expected],
        model=["openai/gpt-4o-mini"],
        config={
            "run_name": f"chroma-vector-rag-{args.mode}",
            "max_concurrency": 1,
        },
    )
    evaluator.run(auto_save=False)


if __name__ == "__main__":
    main()
