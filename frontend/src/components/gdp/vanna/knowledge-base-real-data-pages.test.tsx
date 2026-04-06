/// <reference types="@testing-library/jest-dom/vitest" />
import React from "react"
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { KnowledgeBaseAssetsView } from "./knowledge-base-assets-view"
import { KnowledgeBaseQuestionSqlView } from "./knowledge-base-question-sql-view"
import { KnowledgeBaseRunsView } from "./knowledge-base-runs-view"
import { KnowledgeBaseTrainMethodView } from "./knowledge-base-train-method-view"
import { KnowledgeBaseTrainingView } from "./knowledge-base-training-view"

const pushMock = vi.hoisted(() => vi.fn())
const listTrainingEntriesMock = vi.hoisted(() => vi.fn())
const listAskRunsMock = vi.hoisted(() => vi.fn())
const listHarvestJobsMock = vi.hoisted(() => vi.fn())
const getVannaKnowledgeBaseMock = vi.hoisted(() => vi.fn())
const askVannaSqlMock = vi.hoisted(() => vi.fn())
const promoteAskRunToSqlAssetMock = vi.hoisted(() => vi.fn())
const promoteTrainingEntryToSqlAssetMock = vi.hoisted(() => vi.fn())
const listVannaSqlAssetsMock = vi.hoisted(() => vi.fn())
const listVannaSqlAssetVersionsMock = vi.hoisted(() => vi.fn())
const publishVannaSqlAssetMock = vi.hoisted(() => vi.fn())
const updateVannaSqlAssetMock = vi.hoisted(() => vi.fn())
const archiveVannaSqlAssetMock = vi.hoisted(() => vi.fn())
const deleteTrainingEntryMock = vi.hoisted(() => vi.fn())
const getTrainingEntryMock = vi.hoisted(() => vi.fn())
const updateTrainingEntryMock = vi.hoisted(() => vi.fn())
const tMock = vi.hoisted(
  () => (value: string, vars?: Record<string, string | number>) => {
    const messages: Record<string, string> = {
      "kb.training.feedback.loadFailed": "加载训练知识失败",
      "kb.training.types.question_sql": "SQL 问答对",
      "kb.training.types.documentation": "文档知识",
      "kb.training.actions.createQuestionSql": "新建问答对",
      "kb.training.actions.createDocumentation": "去填写知识",
      "kb.training.searchPlaceholder": "搜索标题、内容或表名...",
      "kb.training.emptyByType": `当前 ${vars?.type ?? ""} 分类下暂无训练知识。`,
      "kb.training.emptyDetail": "当前分类下暂无可查看的知识详情。",
      "kb.training.lifecycle.published": "已发布",
      "kb.training.lifecycle.candidate": "候选",
      "kb.training.quality.verified": "已校验",
      "kb.training.quality.unverified": "未校验",
      "kb.training.sourceKind.manual": "手工录入",
      "kb.training.detail.question": "用户问题",
      "kb.training.detail.emptyQuestion": "暂无问题文本",
      "kb.training.detail.standardSql": "标准 SQL",
      "kb.training.detail.emptySql": "暂无 SQL",
      "kb.training.detail.explanation": "补充说明",
      "kb.training.detail.documentBody": "文档正文",
      "kb.training.detail.emptyDocument": "暂无文档正文",
      "kb.training.detail.emptySchemaSummary": "暂无结构摘要",
      "kb.training.detail.lifecycle": "生命周期",
      "kb.training.detail.quality": "质量",
      "kb.training.detail.schemaTable": "结构 / 表",
      "kb.training.detail.unbound": "未绑定",
      "kb.training.detail.sourceOrigin": "来源",
    }
    return messages[value] ?? value
  }
)

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "7" }),
  useRouter: () => ({ push: pushMock }),
  useSearchParams: () => ({
    get: () => null,
  }),
}))

vi.mock("./vanna-api", () => ({
  getVannaKnowledgeBase: getVannaKnowledgeBaseMock,
  listTrainingEntries: listTrainingEntriesMock,
  listAskRuns: listAskRunsMock,
  listHarvestJobs: listHarvestJobsMock,
  askVannaSql: askVannaSqlMock,
  promoteAskRunToSqlAsset: promoteAskRunToSqlAssetMock,
  promoteTrainingEntryToSqlAsset: promoteTrainingEntryToSqlAssetMock,
  listVannaSqlAssets: listVannaSqlAssetsMock,
  listVannaSqlAssetVersions: listVannaSqlAssetVersionsMock,
  publishVannaSqlAsset: publishVannaSqlAssetMock,
  updateVannaSqlAsset: updateVannaSqlAssetMock,
  archiveVannaSqlAsset: archiveVannaSqlAssetMock,
  deleteTrainingEntry: deleteTrainingEntryMock,
  getTrainingEntry: getTrainingEntryMock,
  updateTrainingEntry: updateTrainingEntryMock,
}))

vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(),
    success: vi.fn(),
  },
}))

vi.mock("@/contexts/i18n-context", () => ({
  useI18n: () => ({
    t: tMock,
  }),
}))

describe("Vanna real-data pages", () => {
  afterEach(() => {
    cleanup()
  })

  beforeEach(() => {
    pushMock.mockReset()
    listTrainingEntriesMock.mockReset()
    listAskRunsMock.mockReset()
    listHarvestJobsMock.mockReset()
    getVannaKnowledgeBaseMock.mockReset()
    askVannaSqlMock.mockReset()
    promoteAskRunToSqlAssetMock.mockReset()
    promoteTrainingEntryToSqlAssetMock.mockReset()
    listVannaSqlAssetsMock.mockReset()
    listVannaSqlAssetVersionsMock.mockReset()
    publishVannaSqlAssetMock.mockReset()
    updateVannaSqlAssetMock.mockReset()
    archiveVannaSqlAssetMock.mockReset()
    deleteTrainingEntryMock.mockReset()
    getTrainingEntryMock.mockReset()
    updateTrainingEntryMock.mockReset()
  })

  it("question-sql view loads the scoped entry type and renders row actions", async () => {
    listTrainingEntriesMock.mockResolvedValue([
      {
        id: 1,
        kb_id: 7,
        datasource_id: 21,
        system_short: "ERP",
        env: "prod",
        entry_code: "question-sql:7:abc",
        entry_type: "question_sql",
        source_kind: "manual",
        lifecycle_status: "published",
        quality_status: "verified",
        title: "查询近一周订单",
        question_text: "查询近一周订单",
        sql_text: "select * from orders",
        sql_explanation: "按创建时间倒序",
        doc_text: null,
        schema_name: "sales",
        table_name: "orders",
        tables_read_json: [],
        columns_read_json: [],
        output_fields_json: [],
        variables_json: [],
        tags_json: [],
        verification_result_json: {},
        create_user_id: 1,
        created_at: "2026-04-05T00:00:00Z",
        updated_at: "2026-04-05T00:00:00Z",
      },
    ])
    listVannaSqlAssetsMock.mockResolvedValue([])

    render(<KnowledgeBaseQuestionSqlView />)

    await waitFor(() => {
      expect(listTrainingEntriesMock).toHaveBeenCalledWith({
        kb_id: 7,
        entry_type: "question_sql",
      })
    })

    expect((await screen.findAllByText("查询近一周订单")).length).toBeGreaterThan(0)
    expect(screen.getByRole("button", { name: /查看详情/i })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /提升为 sql 资产/i })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /修改问答对/i })).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /删除问答对/i })).toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: /查看详情/i }))
    expect(await screen.findByText("SQL 问答对详情")).toBeInTheDocument()
    expect(screen.getByText("用户问题")).toBeInTheDocument()
    expect(screen.getByText("标准 SQL")).toBeInTheDocument()
  })

  it("documentation view can stay empty and still route to create documentation", async () => {
    listTrainingEntriesMock.mockResolvedValue([])
    listVannaSqlAssetsMock.mockResolvedValue([])

    render(<KnowledgeBaseTrainingView entryType="documentation" />)

    await waitFor(() => {
      expect(listTrainingEntriesMock).toHaveBeenCalledWith({
        kb_id: 7,
        entry_type: "documentation",
      })
    })

    expect(screen.getByText("当前 文档知识 分类下暂无训练知识。")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: /去填写知识/i }))
    expect(pushMock).toHaveBeenCalledWith("/knowledge-bases/7/training/documentation/new")
    expect(
      screen.queryByRole("button", { name: /提升为 sql 资产/i })
    ).not.toBeInTheDocument()
  })

  it("question-sql view can promote a training entry into sql asset", async () => {
    listTrainingEntriesMock.mockResolvedValue([
      {
        id: 11,
        kb_id: 7,
        datasource_id: 21,
        system_short: "ERP",
        env: "prod",
        entry_code: "question-sql:7:promote",
        entry_type: "question_sql",
        source_kind: "manual",
        lifecycle_status: "published",
        quality_status: "verified",
        title: "查询管理员用户",
        question_text: "查询管理员用户",
        sql_text: "select * from users where role = 'admin'",
        sql_explanation: "按管理员角色过滤",
        doc_text: null,
        schema_name: "public",
        table_name: "users",
        tables_read_json: [],
        columns_read_json: [],
        output_fields_json: [],
        variables_json: [],
        tags_json: [],
        verification_result_json: {},
        create_user_id: 1,
        created_at: "2026-04-05T00:00:00Z",
        updated_at: "2026-04-05T00:00:00Z",
      },
    ])
    listVannaSqlAssetsMock.mockResolvedValue([])
    promoteTrainingEntryToSqlAssetMock.mockResolvedValue({
      asset: {},
      version: {},
    })

    render(<KnowledgeBaseQuestionSqlView />)

    fireEvent.click(await screen.findByRole("button", { name: /提升为 sql 资产/i }))
    fireEvent.click(await screen.findByRole("button", { name: /创建 sql 资产/i }))

    await waitFor(() => {
      expect(promoteTrainingEntryToSqlAssetMock).toHaveBeenCalledWith(
        11,
        expect.objectContaining({
          asset_code: "training_entry_11",
          name: "查询管理员用户",
          asset_kind: "query",
        })
      )
    })
  })

  it("question-sql view shows promoted asset count in the list and detail", async () => {
    listTrainingEntriesMock.mockResolvedValue([
      {
        id: 12,
        kb_id: 7,
        datasource_id: 21,
        system_short: "ERP",
        env: "prod",
        entry_code: "question-sql:7:promoted",
        entry_type: "question_sql",
        source_kind: "manual",
        lifecycle_status: "published",
        quality_status: "verified",
        title: "查询有效订单",
        question_text: "查询有效订单",
        sql_text: "select * from orders where status = 'valid'",
        sql_explanation: "按有效状态过滤",
        doc_text: null,
        schema_name: "sales",
        table_name: "orders",
        tables_read_json: [],
        columns_read_json: [],
        output_fields_json: [],
        variables_json: [],
        tags_json: [],
        verification_result_json: {},
        create_user_id: 1,
        created_at: "2026-04-05T00:00:00Z",
        updated_at: "2026-04-05T00:00:00Z",
      },
    ])
    listVannaSqlAssetsMock.mockResolvedValue([
      {
        id: 301,
        kb_id: 7,
        datasource_id: 21,
        asset_code: "valid_orders",
        name: "查询有效订单",
        description: null,
        intent_summary: "查询有效订单",
        asset_kind: "query",
        status: "draft",
        system_short: "ERP",
        env: "prod",
        match_keywords: ["有效订单"],
        match_examples: ["查询有效订单"],
        owner_user_id: 1,
        owner_user_name: "root",
        current_version_id: 501,
        origin_ask_run_id: null,
        origin_training_entry_id: 12,
        created_at: "2026-04-05T00:00:00Z",
        updated_at: "2026-04-05T00:00:00Z",
      },
    ])

    render(<KnowledgeBaseQuestionSqlView />)

    expect(await screen.findByText("1 个")).toBeInTheDocument()
    expect(screen.getByText("valid_orders")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: /查看详情/i }))
    expect(await screen.findByText("已提升 1 个资产")).toBeInTheDocument()
  })

  it("assets view can publish a draft asset", async () => {
    getVannaKnowledgeBaseMock.mockResolvedValue({
      id: 7,
      kb_code: "kb_7",
      name: "ERP KB",
      description: null,
      owner_user_id: 1,
      owner_user_name: "root",
      datasource_id: 21,
      datasource_name: "erp-prod",
      system_short: "ERP",
      database_name: "erp",
      env: "prod",
      db_type: "postgresql",
      dialect: "postgresql",
      status: "active",
      default_top_k_sql: 5,
      default_top_k_schema: 8,
      default_top_k_doc: 5,
      embedding_model: null,
      llm_model: null,
      last_train_at: null,
      last_ask_at: null,
      created_at: "2026-04-05T00:00:00Z",
      updated_at: "2026-04-05T00:00:00Z",
    })
    listVannaSqlAssetsMock
      .mockResolvedValueOnce([
        {
          id: 401,
          kb_id: 7,
          datasource_id: 21,
          asset_code: "admin_users",
          name: "管理员用户查询",
          description: null,
          intent_summary: "查管理员账号",
          asset_kind: "query",
          status: "draft",
          system_short: "ERP",
          database_name: "erp",
          env: "prod",
          match_keywords: ["管理员"],
          match_examples: ["查管理员账号"],
          owner_user_id: 1,
          owner_user_name: "root",
          current_version_id: 601,
          origin_ask_run_id: null,
          origin_training_entry_id: 12,
          created_at: "2026-04-05T00:00:00Z",
          updated_at: "2026-04-05T00:00:00Z",
        },
      ])
      .mockResolvedValueOnce([
        {
          id: 401,
          kb_id: 7,
          datasource_id: 21,
          asset_code: "admin_users",
          name: "管理员用户查询",
          description: null,
          intent_summary: "查管理员账号",
          asset_kind: "query",
          status: "published",
          system_short: "ERP",
          database_name: "erp",
          env: "prod",
          match_keywords: ["管理员"],
          match_examples: ["查管理员账号"],
          owner_user_id: 1,
          owner_user_name: "root",
          current_version_id: 601,
          origin_ask_run_id: null,
          origin_training_entry_id: 12,
          created_at: "2026-04-05T00:00:00Z",
          updated_at: "2026-04-06T00:00:00Z",
        },
      ])
    listVannaSqlAssetVersionsMock
      .mockResolvedValueOnce([
        {
          id: 601,
          asset_id: 401,
          version_no: 1,
          version_label: "v1",
          template_sql: "select * from users where role = 'admin'",
          parameter_schema_json: [],
          render_config_json: {},
          statement_kind: "SELECT",
          tables_read_json: ["users"],
          columns_read_json: ["role"],
          output_fields_json: ["id"],
          verification_result_json: {},
          quality_status: "unverified",
          is_published: false,
          published_at: null,
          created_by: "root",
          created_at: "2026-04-05T00:00:00Z",
        },
      ])
      .mockResolvedValueOnce([
        {
          id: 601,
          asset_id: 401,
          version_no: 1,
          version_label: "v1",
          template_sql: "select * from users where role = 'admin'",
          parameter_schema_json: [],
          render_config_json: {},
          statement_kind: "SELECT",
          tables_read_json: ["users"],
          columns_read_json: ["role"],
          output_fields_json: ["id"],
          verification_result_json: {},
          quality_status: "unverified",
          is_published: true,
          published_at: "2026-04-06T00:00:00Z",
          created_by: "root",
          created_at: "2026-04-05T00:00:00Z",
        },
      ])
    publishVannaSqlAssetMock.mockResolvedValue({
      id: 601,
      asset_id: 401,
      version_no: 1,
      version_label: "v1",
      template_sql: "select * from users where role = 'admin'",
      parameter_schema_json: [],
      render_config_json: {},
      statement_kind: "SELECT",
      tables_read_json: ["users"],
      columns_read_json: ["role"],
      output_fields_json: ["id"],
      verification_result_json: {},
      quality_status: "unverified",
      is_published: true,
      published_at: "2026-04-06T00:00:00Z",
      created_by: "root",
      created_at: "2026-04-05T00:00:00Z",
    })

    render(<KnowledgeBaseAssetsView />)

    fireEvent.click(await screen.findByRole("button", { name: "发布" }))

    await waitFor(() => {
      expect(publishVannaSqlAssetMock).toHaveBeenCalledWith(401, {
        version_id: 601,
      })
    })

    expect(await screen.findByText("published")).toBeInTheDocument()
  })

  it("question-sql view can edit a training entry inline", async () => {
    listTrainingEntriesMock.mockResolvedValue([
      {
        id: 18,
        kb_id: 7,
        datasource_id: 21,
        system_short: "ERP",
        env: "prod",
        entry_code: "question-sql:7:edit",
        entry_type: "question_sql",
        source_kind: "manual",
        lifecycle_status: "published",
        quality_status: "verified",
        title: "查询历史订单",
        question_text: "查询历史订单",
        sql_text: "select * from orders",
        sql_explanation: "旧说明",
        doc_text: null,
        schema_name: "sales",
        table_name: "orders",
        tables_read_json: [],
        columns_read_json: [],
        output_fields_json: [],
        variables_json: [],
        tags_json: [],
        verification_result_json: {},
        create_user_id: 1,
        created_at: "2026-04-05T00:00:00Z",
        updated_at: "2026-04-05T00:00:00Z",
      },
    ])
    listVannaSqlAssetsMock.mockResolvedValue([])
    updateTrainingEntryMock.mockResolvedValue({
      id: 18,
      kb_id: 7,
      datasource_id: 21,
      system_short: "ERP",
      env: "prod",
      entry_code: "question-sql:7:edit-updated",
      entry_type: "question_sql",
      source_kind: "manual",
      lifecycle_status: "published",
      quality_status: "verified",
      title: "查询最新订单",
      question_text: "查询最新订单",
      sql_text: "select * from orders order by created_at desc",
      sql_explanation: "新说明",
      doc_text: null,
      schema_name: "sales",
      table_name: "orders",
      tables_read_json: [],
      columns_read_json: [],
      output_fields_json: [],
      variables_json: [],
      tags_json: [],
      verification_result_json: {},
      create_user_id: 1,
      created_at: "2026-04-05T00:00:00Z",
      updated_at: "2026-04-06T00:00:00Z",
    })

    render(<KnowledgeBaseQuestionSqlView />)

    fireEvent.click(await screen.findByRole("button", { name: /修改问答对/i }))
    expect(await screen.findByText("修改 SQL 问答对")).toBeInTheDocument()

    fireEvent.change(screen.getByDisplayValue("查询历史订单"), {
      target: { value: "查询最新订单" },
    })
    fireEvent.change(screen.getByDisplayValue("select * from orders"), {
      target: { value: "select * from orders order by created_at desc" },
    })
    fireEvent.change(screen.getByDisplayValue("旧说明"), {
      target: { value: "新说明" },
    })
    fireEvent.click(screen.getByRole("button", { name: /保存修改/i }))

    await waitFor(() => {
      expect(updateTrainingEntryMock).toHaveBeenCalledWith(
        18,
        expect.objectContaining({
          question: "查询最新订单",
          sql: "select * from orders order by created_at desc",
          sql_explanation: "新说明",
        })
      )
    })

    expect(await screen.findByText("查询最新订单")).toBeInTheDocument()
  })

  it("question-sql view can delete a training entry from the list", async () => {
    listTrainingEntriesMock
      .mockResolvedValueOnce([
        {
          id: 19,
          kb_id: 7,
          datasource_id: 21,
          system_short: "ERP",
          env: "prod",
          entry_code: "question-sql:7:delete",
          entry_type: "question_sql",
          source_kind: "manual",
          lifecycle_status: "published",
          quality_status: "verified",
          title: "删除的问答对",
          question_text: "删除的问答对",
          sql_text: "select * from to_delete",
          sql_explanation: null,
          doc_text: null,
          schema_name: "sales",
          table_name: "to_delete",
          tables_read_json: [],
          columns_read_json: [],
          output_fields_json: [],
          variables_json: [],
          tags_json: [],
          verification_result_json: {},
          create_user_id: 1,
          created_at: "2026-04-05T00:00:00Z",
          updated_at: "2026-04-05T00:00:00Z",
        },
      ])
      .mockResolvedValueOnce([])
    listVannaSqlAssetsMock.mockResolvedValue([])
    deleteTrainingEntryMock.mockResolvedValue({ id: 19, deleted: true })

    render(<KnowledgeBaseQuestionSqlView />)

    fireEvent.click(await screen.findByRole("button", { name: /删除问答对/i }))
    expect(await screen.findByText("删除 SQL 问答对")).toBeInTheDocument()
    fireEvent.click(screen.getByRole("button", { name: /确认删除/i }))

    await waitFor(() => {
      expect(deleteTrainingEntryMock).toHaveBeenCalledWith(19)
    })
    await waitFor(() => {
      expect(screen.getByText("当前没有可展示的 SQL 问答对。")).toBeInTheDocument()
    })
  })

  it("runs view loads ask runs, supports ask and promotion", async () => {
    getVannaKnowledgeBaseMock.mockResolvedValue({
      id: 7,
      kb_code: "kb_erp_prod_default",
      name: "ERP 知识库",
      owner_user_id: 1,
      datasource_id: 21,
      system_short: "ERP",
      env: "prod",
      status: "active",
      default_top_k_sql: 5,
      default_top_k_schema: 9,
      default_top_k_doc: 4,
      created_at: "2026-04-05T00:00:00Z",
      updated_at: "2026-04-05T00:00:00Z",
    })
    listAskRunsMock.mockResolvedValue([
      {
        id: 101,
        kb_id: 7,
        datasource_id: 21,
        system_short: "ERP",
        env: "prod",
        question_text: "查询昨日订单",
        retrieval_snapshot_json: {},
        prompt_snapshot_json: {},
        generated_sql: "select * from orders where dt = current_date - 1",
        sql_confidence: 0.96,
        execution_status: "executed",
        execution_result_json: {},
        create_user_id: 1,
        created_at: "2026-04-05T00:00:00Z",
        updated_at: "2026-04-05T00:00:00Z",
      },
    ])
    listHarvestJobsMock.mockResolvedValue([])
    askVannaSqlMock.mockResolvedValue({
      ask_run_id: 202,
      execution_status: "generated",
      generated_sql: "select * from users where role = 'admin'",
      sql_confidence: 0.92,
      execution_result: null,
    })
    promoteAskRunToSqlAssetMock.mockResolvedValue({
      asset: {},
      version: {},
    })
    listVannaSqlAssetsMock.mockResolvedValue([])

    render(<KnowledgeBaseRunsView />)

    await waitFor(() => {
      expect(getVannaKnowledgeBaseMock).toHaveBeenCalledWith(7)
      expect(listAskRunsMock).toHaveBeenCalledWith({ kb_id: 7 })
    })

    expect(await screen.findByText("查询昨日订单")).toBeInTheDocument()
    expect(screen.getByText("当前生效召回参数")).toBeInTheDocument()
    expect(screen.getByText("SQL 5")).toBeInTheDocument()
    expect(screen.getByText("表结构 9")).toBeInTheDocument()
    expect(screen.getByText("文档 4")).toBeInTheDocument()
    expect(screen.getByText("Ask 记录")).toBeInTheDocument()
    expect(
      screen.queryByRole("tab", { name: /采集记录/i })
    ).not.toBeInTheDocument()

    fireEvent.change(
      screen.getByPlaceholderText("例如：查询所有管理员用户"),
      { target: { value: "查询管理员用户" } }
    )
    fireEvent.click(screen.getByRole("button", { name: /发起 ask/i }))

    await waitFor(() => {
      expect(askVannaSqlMock).toHaveBeenCalledWith({
        datasource_id: 21,
        kb_id: 7,
        question: "查询管理员用户",
        auto_run: false,
        auto_train_on_success: false,
      })
    })

    fireEvent.click(screen.getByRole("button", { name: /提升为 sql 资产/i }))
    fireEvent.click(await screen.findByRole("button", { name: /创建 sql 资产/i }))

    await waitFor(() => {
      expect(promoteAskRunToSqlAssetMock).toHaveBeenCalledWith(
        101,
        expect.objectContaining({
          asset_code: "ask_run_101",
          name: "查询昨日订单",
          asset_kind: "query",
        })
      )
    })
  })

  it("train method view renders backend training paths and shortcuts", async () => {
    getVannaKnowledgeBaseMock.mockResolvedValue({
      id: 7,
      kb_code: "kb_erp_prod_default",
      name: "ERP 知识库",
      owner_user_id: 1,
      datasource_id: 21,
      system_short: "ERP",
      env: "prod",
      status: "active",
      created_at: "2026-04-05T00:00:00Z",
      updated_at: "2026-04-05T00:00:00Z",
    })

    render(<KnowledgeBaseTrainMethodView />)

    await waitFor(() => {
      expect(getVannaKnowledgeBaseMock).toHaveBeenCalledWith(7)
    })

    expect(await screen.findByText("用训练条目把 SQL 知识库喂给 Ask")).toBeInTheDocument()
    expect(screen.getAllByText("POST /api/vanna/train").length).toBeGreaterThan(0)
    expect(
      screen.getByText(/TrainService\.train_question_sql/)
    ).toBeInTheDocument()
    expect(
      screen.getByText(/TrainService\.train_documentation/)
    ).toBeInTheDocument()
    expect(
      screen.getByText(/TrainService\.bootstrap_schema/)
    ).toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: /去新建 sql 问答对/i }))
    expect(pushMock).toHaveBeenCalledWith("/knowledge-bases/7/training/question-sql/new")
  })

  it("assets view renders a single table and supports detail, edit, and delete actions", async () => {
    getVannaKnowledgeBaseMock.mockResolvedValue({
      id: 7,
      kb_code: "kb_erp_prod_default",
      name: "ERP 知识库",
      owner_user_id: 1,
      datasource_id: 21,
      system_short: "ERP",
      database_name: "erp_core",
      env: "prod",
      status: "active",
      created_at: "2026-04-05T00:00:00Z",
      updated_at: "2026-04-05T00:00:00Z",
    })
    listVannaSqlAssetsMock.mockResolvedValue([
      {
        id: 401,
        kb_id: 7,
        datasource_id: 21,
        asset_code: "orders_daily",
        name: "每日订单",
        description: "按天统计订单",
        intent_summary: "按日查询订单",
        asset_kind: "query",
        status: "draft",
        system_short: "ERP",
        database_name: "erp_core",
        env: "prod",
        match_keywords: ["订单", "日报"],
        match_examples: ["昨日订单日报"],
        owner_user_id: 1,
        owner_user_name: "root",
        current_version_id: 901,
        origin_ask_run_id: 100,
        origin_training_entry_id: null,
        created_at: "2026-04-05T00:00:00Z",
        updated_at: "2026-04-05T00:00:00Z",
      },
      {
        id: 402,
        kb_id: 8,
        datasource_id: 22,
        asset_code: "orders_daily_test",
        name: "每日订单-测试",
        description: null,
        intent_summary: "测试环境订单查询",
        asset_kind: "query",
        status: "published",
        system_short: "ERP",
        database_name: "erp_core",
        env: "test",
        match_keywords: ["订单"],
        match_examples: [],
        owner_user_id: 1,
        owner_user_name: "root",
        current_version_id: 902,
        origin_ask_run_id: null,
        origin_training_entry_id: 33,
        created_at: "2026-04-05T00:00:00Z",
        updated_at: "2026-04-05T00:00:00Z",
      },
    ])
    listVannaSqlAssetVersionsMock.mockResolvedValue([
      {
        id: 901,
        asset_id: 401,
        version_no: 1,
        version_label: "v1",
        template_sql: "select * from orders where biz_date = :biz_date",
        parameter_schema_json: [],
        render_config_json: {},
        statement_kind: "SELECT",
        tables_read_json: ["orders"],
        columns_read_json: ["biz_date"],
        output_fields_json: ["order_id"],
        verification_result_json: {},
        quality_status: "unverified",
        is_published: false,
        published_at: null,
        created_by: "root",
        created_at: "2026-04-05T00:00:00Z",
      },
    ])
    updateVannaSqlAssetMock.mockResolvedValue({
      asset: {},
      version: {},
    })
    archiveVannaSqlAssetMock.mockResolvedValue({
      id: 401,
      status: "archived",
    })

    render(<KnowledgeBaseAssetsView />)

    await waitFor(() => {
      expect(getVannaKnowledgeBaseMock).toHaveBeenCalledWith(7)
      expect(listVannaSqlAssetsMock).toHaveBeenCalledWith({
        system_short: "ERP",
        database_name: "erp_core",
      })
    })

    expect(await screen.findByText("ERP SQL 资产列表")).toBeInTheDocument()
    expect(screen.getAllByText("每日订单").length).toBeGreaterThan(0)
    expect(screen.getByText("每日订单-测试")).toBeInTheDocument()

    fireEvent.click(screen.getAllByRole("button", { name: /查看详情/i })[0])
    await waitFor(() => {
      expect(listVannaSqlAssetVersionsMock).toHaveBeenCalledWith(401)
    })
    expect(await screen.findByText("SQL 资产详情")).toBeInTheDocument()
    expect(
      screen.getAllByText("select * from orders where biz_date = :biz_date").length
    ).toBeGreaterThan(0)

    fireEvent.click(screen.getByRole("button", { name: /close/i }))
    fireEvent.click(screen.getAllByRole("button", { name: /^修改$/i })[0])
    expect(await screen.findByText("修改 SQL 资产")).toBeInTheDocument()

    fireEvent.change(screen.getByDisplayValue("orders_daily"), {
      target: { value: "orders_daily_v2" },
    })
    fireEvent.change(screen.getByDisplayValue("每日订单"), {
      target: { value: "每日订单升级版" },
    })
    fireEvent.change(
      screen.getByDisplayValue("select * from orders where biz_date = :biz_date"),
      {
        target: {
          value: "select order_id from orders where biz_date = :biz_date",
        },
      }
    )
    fireEvent.click(screen.getByRole("button", { name: /保存修改/i }))

    await waitFor(() => {
      expect(updateVannaSqlAssetMock).toHaveBeenCalledWith(
        401,
        expect.objectContaining({
          asset_code: "orders_daily_v2",
          name: "每日订单升级版",
          template_sql: "select order_id from orders where biz_date = :biz_date",
        })
      )
    })

    fireEvent.click(screen.getAllByRole("button", { name: /^删除$/i })[0])
    fireEvent.click(await screen.findByRole("button", { name: /确认删除/i }))

    await waitFor(() => {
      expect(archiveVannaSqlAssetMock).toHaveBeenCalledWith(401)
    })
  })
})
