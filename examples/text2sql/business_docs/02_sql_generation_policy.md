# SQL Generation and Interpretation Policy

## Source-of-truth hierarchy

Apply the following order when interpreting an item:

1. The natural-language request defines the intended business operation.
2. The supplied SQL context defines available tables, columns, types, relationships, and sample records.
3. The expected SQL is the evaluation reference, not an invitation to add unstated requirements.
4. General domain knowledge may resolve ordinary language only when it does not conflict with the first two sources.

The dataset assumes each request is answerable from its supplied context. If it is not, classify the item as a possible dataset or schema-context problem rather than rewarding invented SQL.

## Query-construction rules

### Schema grounding

- Match existing table and column names exactly, including unusual capitalization or underscores.
- Reference only objects supplied by the context, except for a new object that the user explicitly asks to create.
- Use aliases only when they improve clarity or are needed to disambiguate a join.
- Infer a join only from compatible keys or relationships supported by the context. Do not join tables merely because their names are related.

### Business semantics

- Preserve every requested filter and literal value.
- Treat date boundaries carefully: “before 2010” normally means earlier than `2010-01-01`; “after 2010” and similar phrases must be checked against the wording and expected inclusivity.
- Use the requested aggregation and group at the level implied by the requested output.
- Preserve requests for distinct values, top or bottom results, ranking, ordering, and limits.
- Return the requested columns and no unrelated fields. `SELECT *` is acceptable only when the request genuinely asks for the full record or the reference semantics require it.
- Do not substitute a convenient proxy for the requested measure. For example, a row count is not a sum, and a maximum single value is not a grouped total.
- Handle `NULL` values using SQL semantics when the request depends on missing or present data.

### Operation type

- Use `SELECT` for analytics and retrieval requests.
- Use `INSERT`, `UPDATE`, or `DELETE` only when the request explicitly asks to add, change, or remove data.
- Mutation predicates must be no broader than the request. A missing or weakened `WHERE` clause is a critical business error.
- Use DDL such as `CREATE TABLE` or `CREATE VIEW` only when the request explicitly asks to define an object.
- A newly created object's name and columns must follow the request exactly; existing referenced objects must still come from the supplied context.

### Dialect and response format

The evaluation executes statements in SQLite. Prefer SQLite-compatible syntax and functions, even when another dialect has a plausible alternative. The response must contain exactly one SQL statement as plain text. Explanations, Markdown fences, multiple candidate statements, and natural-language prefixes are format violations.

The SQL context may contain several semicolon-separated setup statements, including `CREATE TABLE` and `INSERT` statements. These statements establish the evaluation database; they are not part of the answer and must not be copied into the response.

## Severity guidance

- **Critical:** wrong operation type, unrequested mutation, missing mutation predicate, destructive scope expansion, or fabricated schema object.
- **Major:** wrong join, filter, aggregation, grouping level, date boundary, projection, or calculation that changes the business result.
- **Minor:** harmless aliasing or formatting differences that preserve execution and meaning.
- **Not a model error:** an alternative SQL formulation that is semantically equivalent under the supplied context.

## Review checklist

Before accepting a generated statement, verify:

1. Does the SQL perform the operation requested by the user?
2. Are all identifiers grounded in the supplied context?
3. Are filters, literals, boundaries, grouping, ordering, and limits preserved?
4. Is the statement valid for SQLite?
5. Is the output SQL-only and limited to one statement?
6. For a mutation or DDL request, is the scope exact and intentional?
