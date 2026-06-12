"""Minimal vector DB evaluation example using Chroma + qym.

This is designed to test tracing of:
- qym eval/task spans
- LangChain retriever spans
- direct chromadb calls
- Chroma-backed retrieval
- OpenAI-compatible chat completions

Requirements (not installed with qym — this example checks and exits
cleanly if they are missing):

    pip install chromadb langchain-core langchain-chroma openai

Then run:

    python examples/vector_rag_chroma.py --mode langchain
    python examples/vector_rag_chroma.py --mode chromadb

Environment variables:
- OPENAI_API_KEY or OPENROUTER_API_KEY (required)
- OPENAI_BASE_URL or OPENROUTER_BASE_URL (optional)
"""

import argparse
import hashlib
import os
import sys
from typing import List, Optional

try:
    import chromadb
    from langchain_chroma import Chroma
    from langchain_core.documents import Document
    from langchain_core.embeddings import Embeddings
    from openai import AsyncOpenAI
except ImportError as exc:
    print(
        f"[skip] vector_rag_chroma.py is missing an optional dependency ({exc}).\n"
        "       Install them with:\n"
        "           pip install chromadb langchain-core langchain-chroma openai"
    )
    sys.exit(0)

from qym import Evaluator, InMemoryDataset


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


DOCS = [
    ("Paris is the capital of France.", {"title": "France", "source": "seed://countries/france"}),
    ("Tokyo is the capital of Japan.", {"title": "Japan", "source": "seed://countries/japan"}),
    ("Riyadh is the capital of Saudi Arabia.", {"title": "Saudi Arabia", "source": "seed://countries/saudi-arabia"}),
    ("Canberra is the capital of Australia.", {"title": "Australia", "source": "seed://countries/australia"}),
]


def build_retriever():
    docs = [Document(page_content=text, metadata=meta) for text, meta in DOCS]
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
    texts = [text for text, _ in DOCS]
    ids = [f"doc-{i}" for i in range(len(texts))]
    embeddings = SimpleHashEmbeddings().embed_documents(texts)
    metas = [meta for _, meta in DOCS]
    collection.add(ids=ids, documents=texts, embeddings=embeddings, metadatas=metas)
    return collection


def build_dataset() -> InMemoryDataset:
    return InMemoryDataset(
        [
            {"input": "What is the capital of France?", "expected_output": "Paris"},
            {"input": "What is the capital of Japan?", "expected_output": "Tokyo"},
            {"input": "What is the capital of Saudi Arabia?", "expected_output": "Riyadh"},
        ],
        name="chroma-rag-demo",
    )


def build_client() -> AsyncOpenAI:
    api_key = os.getenv("OPENAI_API_KEY") or os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        print("[skip] Set OPENAI_API_KEY or OPENROUTER_API_KEY before running this example.")
        sys.exit(0)
    base_url = os.getenv("OPENAI_BASE_URL") or os.getenv("OPENROUTER_BASE_URL")
    kwargs = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    return AsyncOpenAI(**kwargs)


def contains_expected(output: str, expected: str) -> float:
    return 1.0 if expected.lower() in (output or "").lower() else 0.0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["langchain", "chromadb"], default="langchain")
    args = parser.parse_args()

    client = build_client()

    if args.mode == "langchain":
        retriever = build_retriever()

        async def rag_task(question: str, model_name: Optional[str] = None) -> str:
            docs = retriever.invoke(question)
            context = "\n".join(doc.page_content for doc in docs)
            return await _answer(client, context, question, model_name)

    else:
        collection = build_raw_chromadb_collection()

        async def rag_task(question: str, model_name: Optional[str] = None) -> str:
            embedding = SimpleHashEmbeddings().embed_query(question)
            result = collection.query(
                query_embeddings=[embedding],
                n_results=2,
                include=["documents", "metadatas", "distances"],
            )
            docs = result.get("documents", [[]])[0]
            context = "\n".join(str(doc) for doc in docs if doc)
            return await _answer(client, context, question, model_name)

    evaluator = Evaluator(
        task=rag_task,
        dataset=build_dataset(),
        metrics=[contains_expected],
        model=["openai/gpt-4o-mini"],
        config={
            "run_name": f"chroma-vector-rag-{args.mode}",
            "max_concurrency": 1,
        },
    )
    evaluator.run(auto_save=False)


async def _answer(client: AsyncOpenAI, context: str, question: str, model_name: Optional[str]) -> str:
    model = model_name or "openai/gpt-4o-mini"
    response = await client.chat.completions.create(
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


if __name__ == "__main__":
    main()
