# Text-to-SQL Product Brief

## Purpose

The Text-to-SQL assistant turns a business request written in natural language into executable SQL. It is intended to help analysts, operations teams, and data owners work with unfamiliar databases without manually translating every request into SQL.

Each request contains two authoritative inputs:

1. A natural-language instruction describing the desired result or database action.
2. SQL context containing the relevant database objects and, in many examples, representative seed data.

The assistant returns one SQL statement and no explanatory prose.

## Business outcome

A successful response preserves the user's intent and can be executed against the supplied database context. Correctness is more important than producing SQL that merely looks plausible. The response must not invent a table, column, relationship, filter, or business rule that is absent from the request and schema context.

The example supports more than reporting queries. Its 200-record test set contains:

- 175 analytics and reporting requests;
- 18 data-manipulation requests;
- 5 data-retrieval requests; and
- 2 data-definition requests.

The workload includes basic SQL, aggregation, joins, subqueries, window functions, multiple joins, set operations, and common table expressions. Business domains vary from legal services and rural development to climate, entertainment, manufacturing, and aerospace. Domain knowledge may help interpret wording, but it must never override the supplied schema.

## Users and stakeholders

- **Business requester:** expects the SQL to answer or perform exactly what was requested.
- **Data analyst:** reviews whether projections, filters, calculations, grouping, and ordering preserve the business meaning.
- **Data owner:** verifies that existing database objects are referenced accurately and mutations are properly scoped.
- **Evaluation owner:** determines whether a failure came from the model, the data, the expected answer, or the metric itself.

## Functional requirements

The assistant must:

- use the exact names and compatible data types shown in the supplied context;
- produce a statement appropriate to the requested operation, including `SELECT`, `INSERT`, `UPDATE`, `DELETE`, or DDL when explicitly requested;
- preserve all stated values, dates, comparison boundaries, grouping dimensions, sort direction, and result limits;
- introduce no additional business assumptions;
- return only SQL, without Markdown fences, commentary, caveats, or alternative answers; and
- generate SQL that is executable by SQLite for this evaluation.

When the request is analytical, the assistant must not mutate the database. When the request explicitly asks for a mutation or definition change, the assistant must not replace it with a read-only approximation.

## Out of scope

The example does not provide production authorization, access control, transaction management, privacy classification, query-cost limits, or approval workflows. A correct evaluation result therefore means the SQL matches the supplied synthetic task; it does not mean the statement is approved for execution against a production database.

## Definition of success

A response is successful when it is syntactically valid, grounded in the supplied context, faithful to the complete business request, and semantically equivalent to the expected operation. Syntax validity or a matching execution score alone is not sufficient evidence of business correctness.
