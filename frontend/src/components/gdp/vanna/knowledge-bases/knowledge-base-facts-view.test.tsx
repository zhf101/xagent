/// <reference types="@testing-library/jest-dom/vitest" />
import React from "react"
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { KnowledgeBaseFactsView } from "./knowledge-base-facts-view"

const pushMock = vi.hoisted(() => vi.fn())
const listSchemaTablesMock = vi.hoisted(() => vi.fn())
const listSchemaColumnsMock = vi.hoisted(() => vi.fn())
const updateSchemaColumnAnnotationMock = vi.hoisted(() => vi.fn())
const toastSuccessMock = vi.hoisted(() => vi.fn())

vi.mock("next/navigation", () => ({
  useParams: () => ({ id: "7" }),
  useRouter: () => ({ push: pushMock }),
}))

vi.mock("../shared/vanna-api", () => ({
  listSchemaTables: listSchemaTablesMock,
  listSchemaColumns: listSchemaColumnsMock,
  updateSchemaColumnAnnotation: updateSchemaColumnAnnotationMock,
}))

vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(),
    success: toastSuccessMock,
  },
}))

describe("KnowledgeBaseFactsView", () => {
  afterEach(() => {
    cleanup()
  })

  beforeEach(() => {
    pushMock.mockReset()
    listSchemaTablesMock.mockReset()
    listSchemaColumnsMock.mockReset()
    updateSchemaColumnAnnotationMock.mockReset()
    toastSuccessMock.mockReset()
  })

  it("renders harvested tables and merged editable facts for the current knowledge base", async () => {
    listSchemaTablesMock.mockResolvedValue([
      {
        id: 11,
        kb_id: 7,
        datasource_id: 21,
        harvest_job_id: 31,
        system_short: "ERP",
        env: "prod",
        schema_name: "sales",
        table_name: "orders",
        table_comment: "订单主表",
        table_type: "BASE TABLE",
        table_ddl: "create table sales.orders (...)",
        primary_key_json: ["id"],
        foreign_keys_json: [],
        indexes_json: [],
        constraints_json: [],
        status: "active",
        created_at: "2026-04-05T00:00:00Z",
        updated_at: "2026-04-05T00:00:00Z",
      },
      {
        id: 12,
        kb_id: 7,
        datasource_id: 21,
        harvest_job_id: 31,
        system_short: "ERP",
        env: "prod",
        schema_name: "sales",
        table_name: "customers",
        table_comment: "客户维表",
        table_type: "BASE TABLE",
        table_ddl: null,
        primary_key_json: ["customer_id"],
        foreign_keys_json: [],
        indexes_json: [],
        constraints_json: [],
        status: "stale",
        created_at: "2026-04-05T00:00:00Z",
        updated_at: "2026-04-05T00:00:00Z",
      },
    ])
    listSchemaColumnsMock.mockResolvedValue([
      {
        id: 101,
        table_id: 11,
        kb_id: 7,
        datasource_id: 21,
        system_short: "ERP",
        env: "prod",
        schema_name: "sales",
        table_name: "orders",
        column_name: "id",
        ordinal_position: 1,
        data_type: "bigint",
        udt_name: "int8",
        is_nullable: false,
        default_raw: "nextval('orders_id_seq')",
        default_kind: "sequence",
        column_comment: "订单主键",
        is_primary_key: true,
        is_foreign_key: false,
        foreign_table_name: null,
        foreign_column_name: null,
        is_generated: false,
        generation_expression: null,
        value_source_kind: "generated",
        allowed_values_json: [],
        sample_values_json: [],
        stats_json: {},
        semantic_tags_json: [],
        content_hash: "hash-1",
        business_description: "订单唯一标识",
        comment_override: "订单ID",
        default_value_override: null,
        allowed_values_override_json: [],
        sample_values_override_json: [],
        effective_default_raw: "nextval('orders_id_seq')",
        effective_column_comment: "订单ID",
        effective_allowed_values_json: [],
        effective_sample_values_json: [],
        annotation: null,
        created_at: "2026-04-05T00:00:00Z",
        updated_at: "2026-04-05T00:00:00Z",
      },
      {
        id: 102,
        table_id: 12,
        kb_id: 7,
        datasource_id: 21,
        system_short: "ERP",
        env: "prod",
        schema_name: "sales",
        table_name: "customers",
        column_name: "customer_level",
        ordinal_position: 2,
        data_type: "varchar",
        udt_name: "varchar",
        is_nullable: true,
        default_raw: null,
        default_kind: "none",
        column_comment: "客户等级",
        is_primary_key: false,
        is_foreign_key: false,
        foreign_table_name: null,
        foreign_column_name: null,
        is_generated: false,
        generation_expression: null,
        value_source_kind: "unknown",
        allowed_values_json: ["A", "B", "C"],
        sample_values_json: [],
        stats_json: {},
        semantic_tags_json: [],
        content_hash: "hash-2",
        business_description: null,
        comment_override: null,
        default_value_override: null,
        allowed_values_override_json: [],
        sample_values_override_json: [],
        effective_default_raw: null,
        effective_column_comment: "客户等级",
        effective_allowed_values_json: ["A", "B", "C"],
        effective_sample_values_json: [],
        annotation: null,
        created_at: "2026-04-05T00:00:00Z",
        updated_at: "2026-04-05T00:00:00Z",
      },
    ])

    render(<KnowledgeBaseFactsView />)

    await waitFor(() => {
      expect(listSchemaTablesMock).toHaveBeenCalledWith({ kb_id: 7 })
      expect(listSchemaColumnsMock).toHaveBeenCalledWith({ kb_id: 7 })
    })

    expect(await screen.findByText("orders")).toBeInTheDocument()
    expect(screen.getByText("customers")).toBeInTheDocument()
    expect(screen.getByDisplayValue("订单ID")).toBeInTheDocument()
    expect(screen.getByDisplayValue("订单唯一标识")).toBeInTheDocument()

    fireEvent.click(screen.getByRole("button", { name: /customers/i }))

    expect(await screen.findByDisplayValue("客户等级")).toBeInTheDocument()
    expect(screen.getByDisplayValue("A, B, C")).toBeInTheDocument()
  })

  it("handles legacy column payloads that omit effective value arrays", async () => {
    listSchemaTablesMock.mockResolvedValue([
      {
        id: 11,
        kb_id: 7,
        datasource_id: 21,
        harvest_job_id: 31,
        system_short: "ERP",
        env: "prod",
        schema_name: "sales",
        table_name: "orders",
        table_comment: "订单主表",
        table_type: "BASE TABLE",
        table_ddl: null,
        primary_key_json: ["id"],
        foreign_keys_json: [],
        indexes_json: [],
        constraints_json: [],
        status: "active",
        created_at: "2026-04-05T00:00:00Z",
        updated_at: "2026-04-05T00:00:00Z",
      },
    ])
    listSchemaColumnsMock.mockResolvedValue([
      {
        id: 101,
        table_id: 11,
        kb_id: 7,
        datasource_id: 21,
        system_short: "ERP",
        env: "prod",
        schema_name: "sales",
        table_name: "orders",
        column_name: "order_type",
        ordinal_position: 2,
        data_type: "varchar",
        udt_name: "varchar",
        is_nullable: true,
        default_raw: null,
        default_kind: "none",
        column_comment: "订单类型",
        is_primary_key: false,
        is_foreign_key: false,
        foreign_table_name: null,
        foreign_column_name: null,
        is_generated: false,
        generation_expression: null,
        value_source_kind: "unknown",
        allowed_values_json: [],
        sample_values_json: [],
        stats_json: {},
        semantic_tags_json: [],
        content_hash: "hash-legacy",
        business_description: null,
        comment_override: null,
        default_value_override: null,
        allowed_values_override_json: [],
        sample_values_override_json: [],
        effective_default_raw: null,
        effective_column_comment: "订单类型",
        annotation: null,
        created_at: "2026-04-05T00:00:00Z",
        updated_at: "2026-04-05T00:00:00Z",
      },
    ])

    render(<KnowledgeBaseFactsView />)

    expect(await screen.findByText("orders")).toBeInTheDocument()
    expect(screen.getByDisplayValue("订单类型")).toBeInTheDocument()
  })

  it("saves current table overrides through annotation api", async () => {
    listSchemaTablesMock.mockResolvedValue([
      {
        id: 11,
        kb_id: 7,
        datasource_id: 21,
        harvest_job_id: 31,
        system_short: "ERP",
        env: "prod",
        schema_name: "sales",
        table_name: "orders",
        table_comment: "订单主表",
        table_type: "BASE TABLE",
        table_ddl: null,
        primary_key_json: ["id"],
        foreign_keys_json: [],
        indexes_json: [],
        constraints_json: [],
        status: "active",
        created_at: "2026-04-05T00:00:00Z",
        updated_at: "2026-04-05T00:00:00Z",
      },
    ])
    listSchemaColumnsMock
      .mockResolvedValueOnce([
        {
          id: 101,
          table_id: 11,
          kb_id: 7,
          datasource_id: 21,
          system_short: "ERP",
          env: "prod",
          schema_name: "sales",
          table_name: "orders",
          column_name: "id",
          ordinal_position: 1,
          data_type: "bigint",
          udt_name: "int8",
          is_nullable: false,
          default_raw: "nextval('orders_id_seq')",
          default_kind: "sequence",
          column_comment: "订单主键",
          is_primary_key: true,
          is_foreign_key: false,
          foreign_table_name: null,
          foreign_column_name: null,
          is_generated: false,
          generation_expression: null,
          value_source_kind: "generated",
          allowed_values_json: [],
          sample_values_json: [],
          stats_json: {},
          semantic_tags_json: [],
          content_hash: "hash-1",
          business_description: null,
          comment_override: null,
          default_value_override: null,
          allowed_values_override_json: [],
          sample_values_override_json: [],
          effective_default_raw: "nextval('orders_id_seq')",
          effective_column_comment: "订单主键",
          effective_allowed_values_json: [],
          effective_sample_values_json: [],
          annotation: null,
          created_at: "2026-04-05T00:00:00Z",
          updated_at: "2026-04-05T00:00:00Z",
        },
      ])
      .mockResolvedValueOnce([
        {
          id: 101,
          table_id: 11,
          kb_id: 7,
          datasource_id: 21,
          system_short: "ERP",
          env: "prod",
          schema_name: "sales",
          table_name: "orders",
          column_name: "id",
          ordinal_position: 1,
          data_type: "bigint",
          udt_name: "int8",
          is_nullable: false,
          default_raw: "nextval('orders_id_seq')",
          default_kind: "sequence",
          column_comment: "订单主键",
          is_primary_key: true,
          is_foreign_key: false,
          foreign_table_name: null,
          foreign_column_name: null,
          is_generated: false,
          generation_expression: null,
          value_source_kind: "generated",
          allowed_values_json: [],
          sample_values_json: [],
          stats_json: {},
          semantic_tags_json: [],
          content_hash: "hash-1",
          business_description: "订单唯一标识",
          comment_override: "订单ID",
          default_value_override: null,
          allowed_values_override_json: ["主订单", "补单"],
          sample_values_override_json: [],
          effective_default_raw: "nextval('orders_id_seq')",
          effective_column_comment: "订单ID",
          effective_allowed_values_json: ["主订单", "补单"],
          effective_sample_values_json: [],
          annotation: null,
          created_at: "2026-04-05T00:00:00Z",
          updated_at: "2026-04-05T00:00:00Z",
        },
      ])
    updateSchemaColumnAnnotationMock.mockResolvedValue({})

    render(<KnowledgeBaseFactsView />)

    const commentInputs = await screen.findAllByPlaceholderText("填写字段注释")
    fireEvent.change(commentInputs[0], { target: { value: "订单ID" } })

    const descriptionInputs = screen.getAllByPlaceholderText(
      "补充业务定义、口径约束、使用建议"
    )
    fireEvent.change(descriptionInputs[0], {
      target: { value: "订单唯一标识" },
    })

    const rangeInputs = screen.getAllByPlaceholderText("逗号分隔，如 A, B, C")
    fireEvent.change(rangeInputs[0], {
      target: { value: "主订单, 补单" },
    })

    const saveButton = screen
      .getAllByRole("button", { name: /保存当前表变更/i })
      .find(button => !button.hasAttribute("disabled"))
    expect(saveButton).toBeDefined()
    fireEvent.click(saveButton!)

    await waitFor(() => {
      expect(updateSchemaColumnAnnotationMock).toHaveBeenCalledWith(101, {
        business_description: "订单唯一标识",
        comment_override: "订单ID",
        default_value_override: null,
        allowed_values_override_json: ["主订单", "补单"],
        sample_values_override_json: null,
        update_source: "manual",
      })
    })

    await waitFor(() => {
      expect(toastSuccessMock).toHaveBeenCalledWith("结构事实补充信息已保存")
    })
  })
})
