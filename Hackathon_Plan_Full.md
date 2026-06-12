# Solar O&M Agent Hackathon Plan (Parts 1-9)

## Part 1. Final Recommendation
- **主线选择**: C. O&M copilot with analytics + visualization + decision support.
- **辅助能力**: Ticket / error code 关联解释 (Linking error codes to production impact).
- **原因**: 纯异常检测 (A) 容易陷入模型调优且难以解释；纯 Error Code 映射 (B) 太像传统BI；Copilot (C) 能最好地体现 Agent 价值。结合 Error Code 关联解释作为辅助，可以形成一条极强的证据链：数据异常 -> 对应 Error Code -> 对应 Ticket -> 计算损失 -> 给出建议。这套逻辑 6 小时内完全可以通过 DuckDB (数据处理) + 简单规则 (损失计算) + LLM (总结建议) 跑通，评委一目了然。

## Part 2. MVP Definition
- **用户故事**: 作为 O&M 经理，我早上打开系统，Agent 告诉我昨天 Inverter-A 损失了 500kWh（价值 $xxx），原因是 Error Code 123（过温），且关联到了 Ticket #456，建议我立即派人清洗散热器，并附上了当时的功率曲线对比图。
- **Must-have**: 
  - DuckDB 数据清洗与宽表生成。
  - 基于时间窗口的生产损失计算（简单的 Peer Comparison 或 Expected vs Actual）。
  - Error Code 与生产损失的关联。
  - 基于 Streamlit 的单页面 UI，包含事件选择、图表展示和 Agent 结论。
  - 核心 Agent 的解释与建议生成。
- **Nice-to-have**: 
  - 自然语言对话框提问。
  - 多站点/多逆变器切换。
  - 风险排序 Dashboard。
- **Skip**: 
  - 复杂的机器学习异常检测。
  - 复杂的 RAG 架构或向量数据库。
  - LangGraph 复杂编排。
  - 实时数据流处理。

## Part 3. 6-Hour Execution Plan
- **Hour 1: 数据建模与 DuckDB 初始化**
  - 目标: 跑通数据链路。
  - 任务: 定义 schema，编写 SQL 脚本清洗原始 CSV，生成 `event_impact_wide` 宽表。
  - 产物: `data_pipeline.py` 和 DuckDB 数据库文件。
  - 风险: 字段不匹配。Fallback: 使用 mock 数据先跑通。
- **Hour 2: 核心分析逻辑实现**
  - 目标: 实现生产损失计算和事件关联。
  - 任务: 编写 Python 函数，基于 DuckDB 查询计算 impact，匹配 Error Code。
  - 产物: `analytics_engine.py`。
  - 风险: 损失计算逻辑太复杂。Fallback: 直接用 `(平均功率 - 实际功率) * 时间` 粗略计算。
- **Hour 3: Agent 封装与 API**
  - 目标: 将分析结果转化为自然语言洞察。
  - 任务: 编写 Prompt，将数据指标和 Error Code 喂给 LLM，生成结构化建议。
  - 产物: `agent_core.py`。
  - 风险: LLM 响应慢或格式乱。Fallback: 使用固定模板字符串替换，仅在最后建议部分用 LLM。
- **Hour 4: Streamlit 前端搭建**
  - 目标: 做出可演示的界面。
  - 任务: 编写 `app.py`，实现事件选择器、Plotly 折线图（功率对比）和 Agent 结果展示区。
  - 产物: `app.py`。
  - 风险: UI 调试耗时。Fallback: 放弃交互，直接写死几个经典 Case 展示。
- **Hour 5: 联调与真实案例挖掘**
  - 目标: 找到 1-2 个能完美展示价值的真实数据案例。
  - 任务: 在真实数据中跑通全链路，固化查询参数。
  - 产物: 固化的 Demo Case ID。
  - 风险: 找不到好案例。Fallback: 手工伪造一段有明显特征的异常数据用于演示。
- **Hour 6: 演示准备与 Bug 修复**
  - 目标: 确保演示不翻车。
  - 任务: 录制备用视频，写好演示脚本，清理无用代码。
  - 产物: 演示脚本，录屏。
  - 风险: 现场跑不起来。Fallback: 播放录屏。

## Part 4. Data Contract
- **最小表清单**:
  1. `telemetry_minute` (逆变器分钟级遥测)
  2. `error_events` (逆变器报错记录)
  3. `service_tickets` (运维工单)
- **关键字段**:
  - `telemetry_minute`: `timestamp`, `inverter_id`, `active_power_kw`, `daily_yield_kwh`
  - `error_events`: `start_time`, `end_time`, `inverter_id`, `error_code`, `description`
  - `service_tickets`: `ticket_id`, `create_time`, `close_time`, `inverter_id`, `issue_category`
- **Join 关系**:
  - 基于 `inverter_id` 和时间窗口 (`telemetry_minute.timestamp` BETWEEN `error_events.start_time` AND `error_events.end_time`) 关联。
- **降级策略**:
  - 缺 irradiance: 放弃理论发电量计算，改用同电站其他正常逆变器的平均功率作为 Baseline。
  - 缺 end_time: 假设 error_code 持续时间为 1 小时或直到下一个 error_code 出现。

## Part 5. System Architecture
- **数据层**: CSV/Parquet -> DuckDB (内存/本地文件)。
- **逻辑层 (Python)**:
  - `Data Pipeline`: 执行 SQL 抽取宽表。
  - `Analytics Engine`: 规则计算 (Impact = Baseline - Actual)。
  - `Agent Core`: 组装 Prompt -> 调用 LLM API (OpenAI) -> 解析 JSON 输出。
- **表现层**: Streamlit Web App。
  - 左侧 Sidebar: 选择 Inverter 和时间段 / 预设 Case。
  - 右侧 Main: Plotly 图表 (上) + Agent 分析报告 (下)。
- **必做模块**: DuckDB 查询，规则计算，Streamlit 展示，固定 Prompt 的 LLM 调用。
- **可选模块**: 聊天输入框 (RAG 或动态 SQL)。

## Part 6. DuckDB Plan
- **目录**: `/data` 存放原始数据，`/db` 存放 `.duckdb` 文件。
- **宽表设计 (`event_impact_wide`)**:
  - `event_id`, `inverter_id`, `start_time`, `end_time`, `error_code`, `ticket_id`, `duration_mins`, `avg_power_during_event`, `baseline_power`, `estimated_loss_kwh`
- **核心 SQL 草案 (MVP)**:
```sql
-- 计算事件期间的发电损失 (假设使用同站平均作为 baseline)
WITH peer_avg AS (
    SELECT timestamp, AVG(active_power_kw) as baseline_power
    FROM telemetry_minute
    WHERE inverter_id != 'TARGET_INV'
    GROUP BY timestamp
),
event_telemetry AS (
    SELECT t.timestamp, t.active_power_kw, p.baseline_power
    FROM telemetry_minute t
    JOIN peer_avg p ON t.timestamp = p.timestamp
    WHERE t.inverter_id = 'TARGET_INV'
      AND t.timestamp BETWEEN '2023-01-01 10:00:00' AND '2023-01-01 14:00:00'
)
SELECT 
    SUM(baseline_power - active_power_kw) / 60.0 AS estimated_loss_kwh
FROM event_telemetry
WHERE baseline_power > active_power_kw;
```

## Part 7. App Plan
- **框架**: Streamlit (最省时间，内置图表好用)。
- **页面结构 (单页面)**:
  - **Header**: Solar O&M Copilot
  - **Sidebar**: 
    - "Select Demo Case" (预设几个发现好的典型事件，点击直接看结果，最稳妥)。
    - (可选) "Custom Query" (选时间、选设备)。
  - **Main Area - Top**: Incident Summary (Markdown 卡片，显示损失 kWh，关联 Error Code)。
  - **Main Area - Middle**: Visual Evidence (Plotly 折线图，展示 Actual Power vs Baseline Power，高亮 Error 发生的时间段)。
  - **Main Area - Bottom**: Agent Insights & Actionable Advice (LLM 生成的结构化文本：Cause Analysis, Suggested Actions)。

## Part 8. Agent Workflow
- **主 Agent (O&M Analyst)**:
  - **Trigger**: 用户在 UI 上选择了一个 Event 或 Inverter。
  - **Inputs**: 
    1. 选定时间段的统计数据 (Loss kWh, Duration)。
    2. 相关的 Error Code Description。
    3. 相关的 Ticket History。
  - **Tools**: 仅调用 `analytics_engine` 获取数据字典，不让 LLM 自己写 SQL。
  - **Reasoning**: 
    1. 接收结构化 JSON 数据。
    2. 结合 Error 知识解释为什么会导致这种功率下降。
    3. 给出下一步运维建议 (e.g., 检查保险丝，重启设备)。
  - **Output Schema (JSON)**:
    ```json
    {
      "incident_summary": "Inverter 1A lost 50kWh due to Over-Temperature.",
      "likely_cause": "Cooling fan failure indicated by Error 404.",
      "suggested_action": "Dispatch technician to inspect cooling fans.",
      "confidence": "High"
    }
    ```
- **哪一步用什么**:
  - DuckDB: 数据过滤、聚合、Join。
  - 规则 (Python): Baseline 计算、损失积分计算。
  - LLM: 翻译 Error Code，综合数据生成最终易读的报告和建议。

## Part 9. File-by-file Repo Blueprint
- `/data/` : 存放 mock csv (或真实 csv)
- `/src/`
  - `data_pipeline.py` : DuckDB 初始化与 CSV 导入。
  - `analytics_engine.py` : 执行 SQL，计算损失，提取图表数据。
  - `agent_core.py` : 组装 Prompt，调用 OpenAI API。
- `app.py` : Streamlit 主入口。
- `requirements.txt` : 依赖清单。
- `README.md` : 项目说明与运行指南。
- **开发顺序**: `data_pipeline.py` -> `analytics_engine.py` -> `agent_core.py` -> `app.py`。
# Solar O&M Agent Hackathon Plan (Parts 11-12)

## Part 11. Demo and Judging Pack
- **3分钟 Demo 脚本**:
  - **0:00-0:30 (痛点与价值主张)**: "大家好，O&M 团队每天面对海量 Error Code，很难快速知道哪个最要命。我们的 Solar O&M Copilot 能自动关联遥测数据、报错和工单，不仅告诉你哪里坏了，还告诉你损失了多少钱，以及该怎么办。"
  - **0:30-1:30 (核心展示)**: "看这个 Demo 界面，我们在左侧选择今天发生的一个 Error 404 事件。中间的图表清晰展示了，当报错发生时（红色区域），实际功率（蓝线）立刻大幅偏离了基于其他逆变器算出的基准线（灰线）。系统自动算出这段时间损失了 50 kWh。"
  - **1:30-2:30 (Agent 价值)**: "最重要的是下面的 Agent Insights。它不仅看到了数据，还结合了工单系统，告诉你这是散热风扇故障，并且直接建议你派人去清洗。这不是一个静态 Dashboard，而是一个能给出 actionable advice 的智能助手。"
  - **2:30-3:00 (总结)**: "我们用了 DuckDB 做极速的本地数据处理，结合 LLM 做逻辑推理。这套系统可以直接部署在单机上，明天就能在你们的电站里跑起来。谢谢！"
- **一句话价值主张**: "Turn raw telemetry and cryptic error codes into instant financial impact and actionable O&M advice."
- **首页 5 个核心指标**:
  1. Inverter ID (出问题的设备)
  2. Error Code (具体的报错代码)
  3. Est. Energy Loss (kWh) (预估损失的发电量)
  4. Linked Ticket (关联的工单状态)
  5. Agent Confidence (Agent 给出的建议置信度)
- **评委可能问的问题与回答**:
  - *Q: 你们怎么算损失的？如果没有其他逆变器数据怎么办？* 
    - A: MVP 阶段我们用了同电站其他正常逆变器的平均值作为 baseline (Peer Comparison)。如果没有，我们的 fallback 方案是使用该逆变器前几天的历史同时段均值，或者接入 PVsyst 的理论模型数据。
  - *Q: LLM 幻觉怎么解决？*
    - A: 我们没有让 LLM 直接写 SQL 查数据，而是用 Python+DuckDB 算出确切的损失数字和事件事实，只把结构化的事实交给 LLM 进行“翻译和总结”，从而最大程度限制了幻觉。
- **砍需求方案 (最后 1 小时如果来不及)**:
  - 砍掉：真实数据导入（直接用 `generate_mock_data` 的假数据演示）。
  - 砍掉：复杂的 LLM Prompt（如果 API 调不通，直接用 Python `if-else` 规则输出固定建议）。
  - 砍掉：自然语言对话框（只保留点击选择事件的主流程）。

## Part 12. Next Action
现在立刻应该先生成的 3 个文件（已在 Part 10 中生成完毕，这里说明验证方法）：

1. **`src/data_pipeline.py`**
   - **验证方法**: 运行 `python src/data_pipeline.py`，检查控制台是否输出 "Database initialized successfully."，并在根目录生成 `solar_om.duckdb` 文件以及 `data/` 目录下的 3 个 mock CSV 文件。
2. **`src/analytics_engine.py`**
   - **验证方法**: 在 Python 交互环境或写一个简单的 `test.py` 中运行 `from src.analytics_engine import AnalyticsEngine; e = AnalyticsEngine(); print(e.get_events())`，确认能成功打印出带有 `event_id` 的 DataFrame。
3. **`app.py`**
   - **验证方法**: 运行 `streamlit run app.py`，打开浏览器确认页面能正常渲染，图表能显示红色的 Error Window，且底部的 Agent Insights 区域能显示出内容（即使是 fallback 内容）。
