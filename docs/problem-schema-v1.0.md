# Problem Schema v1.0

这份 schema 用于描述一个可以交给 Agent 或人类研究者求解，并能由 Agent、CI 或人类 Reviewer 验收的开放科学问题。

## JSON 格式

```json
{
  "schema_version": "1.0",
  "problem_id": "problem-id",

  "parent_problem_id": null,
  "subproblem_ids": [],

  "title": "题目名称",

  "abstract": "问题的简短概述。",

  "background": "理解问题所需的背景、定义和已知结果。",

  "references": [
    "参考文献或来源"
  ],

  "previous_progress": [
    "该问题此前已经取得的进展"
  ],

  "problem_statement": "完整、明确、自包含的题面。",

  "scientific_significance": {
    "affected_field": {
      "level": "high",
      "description": "具体说明这个领域会受到什么影响。"
    }
  },

  "solution_difficulty": [
    "一个可能的求解难点",
    "另一个可能的求解难点"
  ],

  "verification_contract": {
    "proof": {
      "contract": "该答案类型的具体验收标准。",
      "ci_contract": "其中可以通过 CI 自动执行的验收部分。"
    },

    "counterexample": {
      "contract": "该答案类型的具体验收标准。",
      "ci_contract": null
    }
  },

  "verification_difficulty": {
    "score": 5,
    "rationale": "综合所有 verification contract，在排除可由 CI 或其他机械程序校验的部分之后，剩余的 Agent 或人类 Reviewer 判断难度。"
  }
}
```

## 字段说明

- `schema_version`：schema 的版本。
- `problem_id`：问题的稳定标识。
- `parent_problem_id`：直接父问题；没有父问题时为 `null`。
- `subproblem_ids`：直接子问题的 ID 列表。
- `title`：简短、明确的题目名称。
- `abstract`：问题的简短概述。
- `background`：理解问题所需的背景、定义和已知结果。
- `references`：相关文献或其他来源。
- `previous_progress`：此前已经取得的研究进展。
- `problem_statement`：完整、明确、自包含的题面。
- `scientific_significance`：受影响领域、影响等级以及具体影响。
- `solution_difficulty`：可能遇到的求解难点列表，不打分。
- `verification_contract`：按答案类型组织的验收合同。它的键就是允许的答案类型，因此不再单独设置 `expected_answer_type`。
- `verification_difficulty`：整个问题的总体验收难度。

`problem_statement` 的问题窗口按整体科学目标判断，而不是按方法、成果或潜在论文的数量判断。一个问题可以同时要求方法开发、计算、分类和物理解释，只要这些结果在科学上相互关联，并共同支撑一个领域专家能够识别其完成边界的目标。“删除一项后其余内容仍可发表”以及“某部分可独立发表”只能作为进一步审查的提示，不能自动判定题目过宽。相对表述在引用文献、上下文或领域惯例足以让专业审稿人稳定理解时也是允许的；不得为了机械化验收而发明任意数值阈值。

## Scientific significance 判定标准

`scientific_significance` 不设置单一总分，而是对每个受影响领域分别判断：

- `high`：解决问题会直接改变该领域的核心认识、方法或能力。
- `medium`：会带来明确进展，或实质性推动若干后续研究。
- `low`：影响较局部、间接或增量性。

每一项必须同时写明：

1. 哪个领域受到影响；
2. 具体会改变什么；
3. 影响是直接的还是间接的。

## Verification contract

`verification_contract` 是一个以答案类型为键的字典。每个答案类型包含：

- `contract`：该类型答案必须提交什么结果和证据，以及 Reviewer 根据什么条件判断通过或不通过。
- `ci_contract`：该合同中可以通过 CI 自动执行的机械验收部分；没有合理的自动验收方式时为 `null`。

CI 是 Continuous Integration，即答案提交或代码更新后，由系统自动运行的机械验收流程。`ci_contract` 应说明自动检查大致接收什么结果、执行什么验证，以及依据什么条件返回通过或失败。

完整验收可以依赖专业领域审稿人的整体判断；CI 只覆盖辅助检查并不构成缺陷。真正的问题是验收合同是否把题面的核心科学目标替换成代理目标、遗漏无关但仍被题面要求的结果，或实质性缩小范围。只有当专业审稿人必须自行发明缺失范围、忽略不相关要求或重新解释题目才能判断完成时，问题窗口才不成立。

## Verification difficulty 评分标准

`verification_difficulty` 是整个问题的一个 `0–10` 总分，不对每种答案类型分别打分。

- `0`：排除机械检查后，没有剩余的 Agent 或人类判断。
- `1–3`：剩余少量独立、局部、标准的推理检查。
- `4–6`：剩余相互依赖的推导，或需要重建题面与答案之间的对应关系。
- `7–9`：剩余较长、脆弱或新颖的推理链，或需要大量代码审查。
- `10`：关键结论无法分解，只能依赖整体专家判断。

### 打分思路

1. 枚举 `verification_contract` 中所有允许的答案类型。
2. 对每种答案类型，找出可由 CI、形式化检查器、测试程序、数值代入、有限枚举或其他机械程序完成的部分。
3. 将这些机械可校验部分排除。即使 CI 尚未实现，只要存在明确的机械检查方法，也不计入剩余判断难度。
4. 判断每类答案还需要 Agent 或人类 Reviewer 审查什么。
5. 综合全部 verification contract，给出一个总分。
6. 在 `rationale` 中说明机械检查部分、剩余判断部分以及总分依据。

`verification_difficulty` 衡量的是验收难度，不是解题难度，也不作为出题或发布阈值。

## 父问题与子问题

如果一个父问题已经把求解和验收委托给子问题，可以使用：

```json
{
  "solution_difficulty": [],
  "verification_contract": null,
  "verification_difficulty": null
}
```

每个实际派发的子问题应提供自己的 `solution_difficulty`、`verification_contract` 和 `verification_difficulty`。
