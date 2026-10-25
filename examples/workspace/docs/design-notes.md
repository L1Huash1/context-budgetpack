# Design notes

These deliberately lower-priority notes explain why a small cart example uses plain functions rather than a payment service. The example never charges a customer or contacts another system. The document is long enough to demonstrate a whole-fragment exclusion when the smaller implementation and tests have already used the budget.

When adopting an explicit context plan, list files that matter to one task. Give the task description and relevant implementation higher priority than general background. A high priority does not guarantee inclusion: a large fragment can still be skipped, allowing a smaller, lower-priority item to fit. The algorithm is stable greedy selection, not a semantic relevance model or an optimal knapsack solver.

The source hashes make later changes visible. They are not signatures, authentication or permission checks. A person who changes the metadata and artifacts together can create a self-consistent bundle. Always review the selected material before sharing it with an agent or another person.

这些说明是合成示例，不包含真实客户、支付、身份信息或生产项目数据。上下文的取舍需要结合实际任务，不应该仅由文件名或固定优先级决定。
