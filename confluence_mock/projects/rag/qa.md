# QA

**Project:** RAG

This page documents evaluation runs for the **QA** task. Each run includes performance metrics, configuration details, and approval status.

## Evaluation History

| Run ID | Date | Author |
|:-------|:-----|:-------|
| [ragbench-qwen/qwen3-235b-a22b-2507-251205-0007-2](#ragbench-qwenqwen3-235b-a22b-2507-251205-0007-2) | December 05, 2025 at 00:33 | @ahmed.hassan |
| [ragbench-openai/gpt-oss-120b-251205-0002-1](#ragbench-openaigpt-oss-120b-251205-0002-1) | December 05, 2025 at 00:50 | @ahmed.hassan |
| [ragbench-meta-llama/llama-4-maverick-251205-0002](#ragbench-meta-llamallama-4-maverick-251205-0002) | December 05, 2025 at 00:53 | @omar.khalid |
| [ragbench-qwen/qwen3-235b-a22b-2507-251205-0145-1](#ragbench-qwenqwen3-235b-a22b-2507-251205-0145-1) | December 05, 2025 at 19:24 | @fhussein |

---

## ragbench-qwen/qwen3-235b-a22b-2507-251205-0007-2

> **Published:** December 05, 2025 at 00:33 | **Author:** @ahmed.hassan

### Summary

Baseline evaluation for the QA task using Qwen3 model. This establishes our benchmark for comparing future model improvements.

### Performance Metrics

| Metric | Score |
|:-------|------:|
| Correctness | 66.9% |
| Faithfulness | 92.8% |

### Run Configuration

| Parameter | Value |
|:----------|:------|
| **Model** | qwen3-235b-a22b-2507 |
| **Dataset** | ragbench-100 |
| **Total Samples** | 98 |
| **Success Rate** | 100.0% (98/98) |
| **Errors** | 0 |
| **Avg Response Time** | 1.4s |
| **Traces** | [View in Langfuse](https://langfuse.example.com/project/abc123/sessions/run-001) |

### Source Control

| | |
|:--|:--|
| **Branch** | `main` |
| **Commit** | `8df95c2` |

---

## ragbench-openai/gpt-oss-120b-251205-0002-1

> **Published:** December 05, 2025 at 00:50 | **Author:** @ahmed.hassan

### Summary

Testing OpenAI GPT OSS model for comparison. Some errors occurred during evaluation that need investigation.

### Performance Metrics

| Metric | Score |
|:-------|------:|
| Correctness | 44.6% |
| Faithfulness | 93.7% |

### Run Configuration

| Parameter | Value |
|:----------|:------|
| **Model** | gpt-oss-120b |
| **Dataset** | ragbench-100 |
| **Total Samples** | 98 |
| **Success Rate** | 95.9% (94/98) |
| **Errors** | 4 |
| **Avg Response Time** | 3.5s |
| **Traces** | [View in Langfuse](https://langfuse.example.com/project/abc123/sessions/run-002) |

### Source Control

| | |
|:--|:--|
| **Branch** | `main` |
| **Commit** | `8df95c2` |

---

## ragbench-meta-llama/llama-4-maverick-251205-0002

> **Published:** December 05, 2025 at 00:53 | **Author:** @omar.khalid

### Summary

New best score achieved with Llama 4 Maverick model. Recommended for production deployment pending final review.

### Performance Metrics

| Metric | Score |
|:-------|------:|
| Correctness | 47.9% |
| Faithfulness | 85.6% |

### Run Configuration

| Parameter | Value |
|:----------|:------|
| **Model** | llama-4-maverick |
| **Dataset** | ragbench-100 |
| **Total Samples** | 98 |
| **Success Rate** | 100.0% (98/98) |
| **Errors** | 0 |
| **Avg Response Time** | 1.7s |
| **Traces** | [View in Langfuse](https://langfuse.example.com/project/abc123/sessions/run-003) |

### Source Control

| | |
|:--|:--|
| **Branch** | `main` |
| **Commit** | `8df95c2` |

---

## ragbench-qwen/qwen3-235b-a22b-2507-251205-0145-1

> **Published:** December 05, 2025 at 19:24 | **Author:** @fhussein

### Summary

Baseline

### Performance Metrics

| Metric | Score |
|:-------|------:|
| Correctness | 68.1% |
| Faithfulness | 92.7% |

### Run Configuration

| Parameter | Value |
|:----------|:------|
| **Model** | qwen3-235b-a22b-2507 |
| **Dataset** | ragbench-100 |
| **Total Samples** | 98 |
| **Success Rate** | 100.0% (98/98) |
| **Errors** | 0 |
| **Avg Response Time** | 1.3s |
| **Traces** | [View in Langfuse](https://cloud.langfuse.com/project/cmdizrkpp007tad06a2op5801/datasets/ragbench-100/runs/ragbench-qwen%2Fqwen3-235b-a22b-2507-251205-0145-1) |

### Source Control

| | |
|:--|:--|
| **Branch** | `main` |
| **Commit** | `8df95c2` |
