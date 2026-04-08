-- xagent database schema backup
-- Generated: 2026-04-08 17:47:25


-- ============================================
-- Schema: public
-- ============================================

-- Table: public.agents
CREATE TABLE public.agents (
    id integer DEFAULT nextval('agents_id_seq'::regclass) NOT NULL,
    user_id integer NOT NULL,
    name character varying(200) NOT NULL,
    description text,
    instructions text,
    execution_mode character varying(20) NOT NULL,
    models json,
    knowledge_bases json,
    skills json,
    tool_categories json,
    suggested_prompts json,
    logo_url character varying(500),
    status USER-DEFINED NOT NULL,
    published_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    PRIMARY KEY (id)
);
ALTER TABLE public.agents ADD CONSTRAINT agents_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);
CREATE INDEX ix_agents_user_id ON public.agents USING btree (user_id);
CREATE INDEX ix_agents_id ON public.agents USING btree (id);
COMMENT ON TABLE public.agents IS '自定义Agent配置表';
COMMENT ON COLUMN public.agents.id IS 'Agent ID';
COMMENT ON COLUMN public.agents.user_id IS '用户ID';
COMMENT ON COLUMN public.agents.name IS 'Agent名称';
COMMENT ON COLUMN public.agents.description IS 'Agent描述';
COMMENT ON COLUMN public.agents.instructions IS '系统指令';
COMMENT ON COLUMN public.agents.execution_mode IS '执行模式(simple/react/graph)';
COMMENT ON COLUMN public.agents.models IS '模型配置';
COMMENT ON COLUMN public.agents.knowledge_bases IS '知识库列表';
COMMENT ON COLUMN public.agents.skills IS '技能列表';
COMMENT ON COLUMN public.agents.tool_categories IS '工具分类列表';
COMMENT ON COLUMN public.agents.suggested_prompts IS '建议提示词';
COMMENT ON COLUMN public.agents.logo_url IS 'Logo地址';
COMMENT ON COLUMN public.agents.status IS '状态(draft/published/archived)';
COMMENT ON COLUMN public.agents.published_at IS '发布时间';
COMMENT ON COLUMN public.agents.created_at IS '创建时间';
COMMENT ON COLUMN public.agents.updated_at IS '更新时间';


-- Table: public.alembic_version
CREATE TABLE public.alembic_version (
    version_num character varying(255) NOT NULL,
    PRIMARY KEY (version_num)
);


-- Table: public.dag_executions
CREATE TABLE public.dag_executions (
    id integer DEFAULT nextval('dag_executions_id_seq'::regclass) NOT NULL,
    task_id integer NOT NULL,
    phase USER-DEFINED,
    progress_percentage double precision,
    completed_steps integer,
    total_steps integer,
    execution_time double precision,
    start_time timestamp with time zone,
    end_time timestamp with time zone,
    current_plan json,
    skipped_steps json,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    PRIMARY KEY (id)
);
ALTER TABLE public.dag_executions ADD CONSTRAINT dag_executions_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.tasks(id);
CREATE UNIQUE INDEX dag_executions_task_id_key ON public.dag_executions USING btree (task_id);
CREATE INDEX ix_dag_executions_id ON public.dag_executions USING btree (id);
COMMENT ON TABLE public.dag_executions IS 'DAG执行状态表';
COMMENT ON COLUMN public.dag_executions.id IS '执行ID';
COMMENT ON COLUMN public.dag_executions.task_id IS '任务ID';
COMMENT ON COLUMN public.dag_executions.phase IS '执行阶段';
COMMENT ON COLUMN public.dag_executions.progress_percentage IS '进度百分比';
COMMENT ON COLUMN public.dag_executions.completed_steps IS '已完成步骤数';
COMMENT ON COLUMN public.dag_executions.total_steps IS '总步骤数';
COMMENT ON COLUMN public.dag_executions.execution_time IS '执行时间(秒)';
COMMENT ON COLUMN public.dag_executions.start_time IS '开始时间';
COMMENT ON COLUMN public.dag_executions.end_time IS '结束时间';
COMMENT ON COLUMN public.dag_executions.current_plan IS '当前计划';
COMMENT ON COLUMN public.dag_executions.skipped_steps IS '跳过的步骤';
COMMENT ON COLUMN public.dag_executions.created_at IS '创建时间';
COMMENT ON COLUMN public.dag_executions.updated_at IS '更新时间';


-- Table: public.gdp_http_resources
CREATE TABLE public.gdp_http_resources (
    id integer DEFAULT nextval('gdp_http_resources_id_seq'::regclass) NOT NULL,
    resource_key character varying(255) NOT NULL,
    system_short character varying(64) NOT NULL,
    create_user_id integer NOT NULL,
    create_user_name character varying(255),
    visibility character varying(50) NOT NULL,
    status smallint NOT NULL,
    summary text,
    tags_json json NOT NULL,
    tool_name character varying(255) NOT NULL,
    tool_description text NOT NULL,
    input_schema_json json NOT NULL,
    output_schema_json json NOT NULL,
    annotations_json json NOT NULL,
    method character varying(10) NOT NULL,
    url_mode character varying(20) NOT NULL,
    direct_url text,
    sys_label character varying(255),
    url_suffix text,
    args_position_json json NOT NULL,
    request_template_json json NOT NULL,
    response_template_json json NOT NULL,
    error_response_template text,
    auth_json json NOT NULL,
    headers_json json NOT NULL,
    timeout_seconds integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    PRIMARY KEY (id)
);
ALTER TABLE public.gdp_http_resources ADD CONSTRAINT gdp_http_resources_create_user_id_fkey FOREIGN KEY (create_user_id) REFERENCES public.users(id);
CREATE INDEX ix_gdp_http_resources_id ON public.gdp_http_resources USING btree (id);
CREATE UNIQUE INDEX ix_gdp_http_resources_resource_key ON public.gdp_http_resources USING btree (resource_key);
CREATE INDEX ix_gdp_http_resources_status ON public.gdp_http_resources USING btree (status);
CREATE INDEX ix_gdp_http_resources_create_user_id ON public.gdp_http_resources USING btree (create_user_id);
CREATE INDEX ix_gdp_http_resources_system_short ON public.gdp_http_resources USING btree (system_short);
COMMENT ON TABLE public.gdp_http_resources IS 'HTTP资产表';
COMMENT ON COLUMN public.gdp_http_resources.id IS 'HTTP资源ID';
COMMENT ON COLUMN public.gdp_http_resources.resource_key IS '资源唯一键';
COMMENT ON COLUMN public.gdp_http_resources.system_short IS '系统简称';
COMMENT ON COLUMN public.gdp_http_resources.create_user_id IS '创建用户ID';
COMMENT ON COLUMN public.gdp_http_resources.create_user_name IS '创建用户名';
COMMENT ON COLUMN public.gdp_http_resources.visibility IS '可见性(private/shared/global)';
COMMENT ON COLUMN public.gdp_http_resources.status IS '状态(0:inactive,1:active,2:archived)';
COMMENT ON COLUMN public.gdp_http_resources.summary IS '资源摘要';
COMMENT ON COLUMN public.gdp_http_resources.tags_json IS '标签列表(JSON格式)';
COMMENT ON COLUMN public.gdp_http_resources.tool_name IS '工具名称';
COMMENT ON COLUMN public.gdp_http_resources.tool_description IS '工具描述';
COMMENT ON COLUMN public.gdp_http_resources.input_schema_json IS '输入Schema(JSON格式)';
COMMENT ON COLUMN public.gdp_http_resources.output_schema_json IS '输出Schema(JSON格式)';
COMMENT ON COLUMN public.gdp_http_resources.annotations_json IS '注解(JSON格式)';
COMMENT ON COLUMN public.gdp_http_resources.method IS 'HTTP方法';
COMMENT ON COLUMN public.gdp_http_resources.url_mode IS 'URL模式(direct/tag)';
COMMENT ON COLUMN public.gdp_http_resources.direct_url IS '直接URL';
COMMENT ON COLUMN public.gdp_http_resources.sys_label IS '系统标签';
COMMENT ON COLUMN public.gdp_http_resources.url_suffix IS 'URL后缀';
COMMENT ON COLUMN public.gdp_http_resources.args_position_json IS '参数位置(JSON格式)';
COMMENT ON COLUMN public.gdp_http_resources.request_template_json IS '请求模板(JSON格式)';
COMMENT ON COLUMN public.gdp_http_resources.response_template_json IS '响应模板(JSON格式)';
COMMENT ON COLUMN public.gdp_http_resources.error_response_template IS '错误响应模板';
COMMENT ON COLUMN public.gdp_http_resources.auth_json IS '认证配置(JSON格式)';
COMMENT ON COLUMN public.gdp_http_resources.headers_json IS '请求头(JSON格式)';
COMMENT ON COLUMN public.gdp_http_resources.timeout_seconds IS '超时时间(秒)';
COMMENT ON COLUMN public.gdp_http_resources.created_at IS '创建时间';
COMMENT ON COLUMN public.gdp_http_resources.updated_at IS '更新时间';


-- Table: public.mcp_servers
CREATE TABLE public.mcp_servers (
    id integer DEFAULT nextval('mcp_servers_id_seq'::regclass) NOT NULL,
    name character varying(100) NOT NULL,
    description text,
    managed character varying(20) NOT NULL,
    transport character varying(50) NOT NULL,
    command character varying(500),
    args json,
    url character varying(500),
    env json,
    cwd character varying(500),
    headers json,
    docker_url character varying(500),
    docker_image character varying(200),
    docker_environment json,
    docker_working_dir character varying(500),
    volumes json,
    bind_ports json,
    restart_policy character varying(50) NOT NULL,
    auto_start boolean,
    container_id character varying(100),
    container_name character varying(200),
    container_logs json,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    PRIMARY KEY (id)
);
CREATE UNIQUE INDEX mcp_servers_name_key ON public.mcp_servers USING btree (name);
CREATE INDEX ix_mcp_servers_id ON public.mcp_servers USING btree (id);
COMMENT ON TABLE public.mcp_servers IS 'MCP服务器配置表';
COMMENT ON COLUMN public.mcp_servers.id IS '服务器ID';
COMMENT ON COLUMN public.mcp_servers.name IS '服务器名称';
COMMENT ON COLUMN public.mcp_servers.description IS '服务器描述';
COMMENT ON COLUMN public.mcp_servers.managed IS '管理方式(internal/external)';
COMMENT ON COLUMN public.mcp_servers.transport IS '传输方式(stdio/sse/websocket/streamable_http)';
COMMENT ON COLUMN public.mcp_servers.command IS '启动命令';
COMMENT ON COLUMN public.mcp_servers.args IS '启动参数(JSON数组)';
COMMENT ON COLUMN public.mcp_servers.url IS '服务URL';
COMMENT ON COLUMN public.mcp_servers.env IS '环境变量(JSON对象)';
COMMENT ON COLUMN public.mcp_servers.cwd IS '工作目录';
COMMENT ON COLUMN public.mcp_servers.headers IS '请求头(JSON对象)';
COMMENT ON COLUMN public.mcp_servers.docker_url IS 'Docker地址';
COMMENT ON COLUMN public.mcp_servers.docker_image IS 'Docker镜像';
COMMENT ON COLUMN public.mcp_servers.docker_environment IS 'Docker环境变量';
COMMENT ON COLUMN public.mcp_servers.docker_working_dir IS 'Docker工作目录';
COMMENT ON COLUMN public.mcp_servers.volumes IS '挂载卷';
COMMENT ON COLUMN public.mcp_servers.bind_ports IS '端口映射';
COMMENT ON COLUMN public.mcp_servers.restart_policy IS '重启策略';
COMMENT ON COLUMN public.mcp_servers.auto_start IS '是否自动启动';
COMMENT ON COLUMN public.mcp_servers.container_id IS '容器ID';
COMMENT ON COLUMN public.mcp_servers.container_name IS '容器名称';
COMMENT ON COLUMN public.mcp_servers.container_logs IS '容器日志';
COMMENT ON COLUMN public.mcp_servers.created_at IS '创建时间';
COMMENT ON COLUMN public.mcp_servers.updated_at IS '更新时间';


-- Table: public.memory_jobs
CREATE TABLE public.memory_jobs (
    id integer DEFAULT nextval('memory_jobs_id_seq'::regclass) NOT NULL,
    job_type character varying(64) NOT NULL,
    status character varying(32) DEFAULT 'pending'::character varying NOT NULL,
    priority integer DEFAULT 100 NOT NULL,
    payload_json json NOT NULL,
    dedupe_key character varying(255),
    source_task_id character varying(255),
    source_session_id character varying(255),
    source_user_id integer,
    source_project_id character varying(255),
    attempt_count integer DEFAULT 0 NOT NULL,
    max_attempts integer DEFAULT 3 NOT NULL,
    available_at timestamp with time zone DEFAULT now() NOT NULL,
    lease_until timestamp with time zone,
    locked_by character varying(255),
    last_error text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    started_at timestamp with time zone,
    finished_at timestamp with time zone,
    PRIMARY KEY (id)
);
CREATE INDEX ix_memory_jobs_available_at ON public.memory_jobs USING btree (available_at);
CREATE INDEX ix_memory_jobs_status_available_at ON public.memory_jobs USING btree (status, available_at);
CREATE INDEX ix_memory_jobs_id ON public.memory_jobs USING btree (id);
CREATE INDEX ix_memory_jobs_source_user_id ON public.memory_jobs USING btree (source_user_id);
CREATE INDEX ix_memory_jobs_source_user_session_created ON public.memory_jobs USING btree (source_user_id, source_session_id, created_at);
CREATE INDEX ix_memory_jobs_dedupe_key ON public.memory_jobs USING btree (dedupe_key);
CREATE INDEX ix_memory_jobs_source_project_id ON public.memory_jobs USING btree (source_project_id);
CREATE INDEX ix_memory_jobs_job_type ON public.memory_jobs USING btree (job_type);
CREATE INDEX ix_memory_jobs_source_task_id ON public.memory_jobs USING btree (source_task_id);
CREATE INDEX ix_memory_jobs_lease_until ON public.memory_jobs USING btree (lease_until);
CREATE INDEX ix_memory_jobs_dedupe_key_status ON public.memory_jobs USING btree (dedupe_key, status);
CREATE INDEX ix_memory_jobs_job_type_status_available_at ON public.memory_jobs USING btree (job_type, status, available_at);
CREATE INDEX ix_memory_jobs_status ON public.memory_jobs USING btree (status);
CREATE INDEX ix_memory_jobs_source_session_id ON public.memory_jobs USING btree (source_session_id);
COMMENT ON TABLE public.memory_jobs IS '后台记忆治理任务表';
COMMENT ON COLUMN public.memory_jobs.id IS '任务ID';
COMMENT ON COLUMN public.memory_jobs.job_type IS '任务类型';
COMMENT ON COLUMN public.memory_jobs.status IS '任务状态(pending/running/completed/failed)';
COMMENT ON COLUMN public.memory_jobs.priority IS '优先级';
COMMENT ON COLUMN public.memory_jobs.payload_json IS '任务参数(JSON)';
COMMENT ON COLUMN public.memory_jobs.dedupe_key IS '去重键';
COMMENT ON COLUMN public.memory_jobs.source_task_id IS '来源任务ID';
COMMENT ON COLUMN public.memory_jobs.source_session_id IS '来源会话ID';
COMMENT ON COLUMN public.memory_jobs.source_user_id IS '来源用户ID';
COMMENT ON COLUMN public.memory_jobs.source_project_id IS '来源项目ID';
COMMENT ON COLUMN public.memory_jobs.attempt_count IS '尝试次数';
COMMENT ON COLUMN public.memory_jobs.max_attempts IS '最大尝试次数';
COMMENT ON COLUMN public.memory_jobs.available_at IS '可执行时间';
COMMENT ON COLUMN public.memory_jobs.lease_until IS '租约过期时间';
COMMENT ON COLUMN public.memory_jobs.locked_by IS '锁定者';
COMMENT ON COLUMN public.memory_jobs.last_error IS '最后错误信息';
COMMENT ON COLUMN public.memory_jobs.created_at IS '创建时间';
COMMENT ON COLUMN public.memory_jobs.updated_at IS '更新时间';
COMMENT ON COLUMN public.memory_jobs.started_at IS '开始时间';
COMMENT ON COLUMN public.memory_jobs.finished_at IS '完成时间';


-- Table: public.models
CREATE TABLE public.models (
    id integer DEFAULT nextval('models_id_seq'::regclass) NOT NULL,
    model_id character varying(100) NOT NULL,
    category character varying(20) NOT NULL,
    model_provider character varying(50) NOT NULL,
    model_name character varying(100) NOT NULL,
    base_url character varying(500),
    temperature double precision,
    max_tokens integer,
    dimension integer,
    abilities json,
    description text,
    max_retries integer,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone,
    is_active boolean,
    _api_key_encrypted character varying(500) NOT NULL,
    PRIMARY KEY (id)
);
CREATE INDEX ix_models_id ON public.models USING btree (id);
CREATE UNIQUE INDEX ix_models_model_id ON public.models USING btree (model_id);
COMMENT ON TABLE public.models IS '模型配置表';


-- Table: public.sandbox_info
CREATE TABLE public.sandbox_info (
    id integer DEFAULT nextval('sandbox_info_id_seq'::regclass) NOT NULL,
    sandbox_type character varying(50) NOT NULL,
    name character varying(255) NOT NULL,
    state character varying(50) NOT NULL,
    template text,
    config text,
    created_at timestamp with time zone,
    updated_at timestamp with time zone,
    PRIMARY KEY (id)
);
CREATE UNIQUE INDEX uix_name_sandbox_type ON public.sandbox_info USING btree (name, sandbox_type);
CREATE INDEX ix_sandbox_info_name ON public.sandbox_info USING btree (name);
CREATE INDEX ix_sandbox_info_sandbox_type ON public.sandbox_info USING btree (sandbox_type);
COMMENT ON TABLE public.sandbox_info IS '沙箱信息表';


-- Table: public.system_environment_endpoints
CREATE TABLE public.system_environment_endpoints (
    id integer DEFAULT nextval('system_environment_endpoints_id_seq'::regclass) NOT NULL,
    system_short character varying(64) NOT NULL,
    env_label character varying(64) NOT NULL,
    base_url text NOT NULL,
    description text,
    status character varying(32) NOT NULL,
    created_by integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    PRIMARY KEY (id)
);
ALTER TABLE public.system_environment_endpoints ADD CONSTRAINT system_environment_endpoints_system_short_fkey FOREIGN KEY (system_short) REFERENCES public.system_registry(system_short);
CREATE UNIQUE INDEX uq_system_environment_endpoint ON public.system_environment_endpoints USING btree (system_short, env_label);
CREATE INDEX ix_system_environment_endpoints_created_by ON public.system_environment_endpoints USING btree (created_by);
CREATE INDEX ix_system_environment_endpoints_env_label ON public.system_environment_endpoints USING btree (env_label);
CREATE INDEX ix_system_environment_endpoints_id ON public.system_environment_endpoints USING btree (id);
CREATE INDEX ix_system_environment_endpoints_system_short ON public.system_environment_endpoints USING btree (system_short);
CREATE INDEX ix_system_environment_endpoints_status ON public.system_environment_endpoints USING btree (status);
COMMENT ON TABLE public.system_environment_endpoints IS '系统环境地址映射表';
COMMENT ON COLUMN public.system_environment_endpoints.id IS '端点ID';
COMMENT ON COLUMN public.system_environment_endpoints.system_short IS '系统简称';
COMMENT ON COLUMN public.system_environment_endpoints.env_label IS '环境标签(DEV/UAT/PROD/INTERNAL)';
COMMENT ON COLUMN public.system_environment_endpoints.base_url IS '基础URL';
COMMENT ON COLUMN public.system_environment_endpoints.description IS '环境描述';
COMMENT ON COLUMN public.system_environment_endpoints.status IS '状态(active/disabled)';
COMMENT ON COLUMN public.system_environment_endpoints.created_by IS '创建人ID';
COMMENT ON COLUMN public.system_environment_endpoints.created_at IS '创建时间';
COMMENT ON COLUMN public.system_environment_endpoints.updated_at IS '更新时间';


-- Table: public.system_registry
CREATE TABLE public.system_registry (
    system_short character varying(64) NOT NULL,
    display_name character varying(128) NOT NULL,
    description text,
    status character varying(32) NOT NULL,
    created_by integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    PRIMARY KEY (system_short)
);
CREATE INDEX ix_system_registry_status ON public.system_registry USING btree (status);
CREATE INDEX ix_system_registry_created_by ON public.system_registry USING btree (created_by);
CREATE INDEX ix_system_registry_system_short ON public.system_registry USING btree (system_short);
COMMENT ON TABLE public.system_registry IS '系统主数据表';
COMMENT ON COLUMN public.system_registry.system_short IS '系统唯一简称';
COMMENT ON COLUMN public.system_registry.display_name IS '系统显示名称';
COMMENT ON COLUMN public.system_registry.description IS '系统描述';
COMMENT ON COLUMN public.system_registry.status IS '系统状态(active/disabled)';
COMMENT ON COLUMN public.system_registry.created_by IS '创建人ID';
COMMENT ON COLUMN public.system_registry.created_at IS '创建时间';
COMMENT ON COLUMN public.system_registry.updated_at IS '更新时间';


-- Table: public.system_settings
CREATE TABLE public.system_settings (
    id integer DEFAULT nextval('system_settings_id_seq'::regclass) NOT NULL,
    key character varying(128) NOT NULL,
    value text NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone,
    PRIMARY KEY (id)
);
CREATE UNIQUE INDEX ix_system_settings_key ON public.system_settings USING btree (key);
CREATE INDEX ix_system_settings_id ON public.system_settings USING btree (id);
COMMENT ON TABLE public.system_settings IS '系统设置表';


-- Table: public.task_chat_messages
CREATE TABLE public.task_chat_messages (
    id integer DEFAULT nextval('task_chat_messages_id_seq'::regclass) NOT NULL,
    task_id integer NOT NULL,
    user_id integer NOT NULL,
    role character varying(32) NOT NULL,
    content text NOT NULL,
    message_type character varying(64) NOT NULL,
    interactions json,
    created_at timestamp with time zone DEFAULT now(),
    PRIMARY KEY (id)
);
ALTER TABLE public.task_chat_messages ADD CONSTRAINT task_chat_messages_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.tasks(id);
ALTER TABLE public.task_chat_messages ADD CONSTRAINT task_chat_messages_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);
CREATE INDEX ix_task_chat_messages_id ON public.task_chat_messages USING btree (id);
CREATE INDEX ix_task_chat_messages_task_id ON public.task_chat_messages USING btree (task_id);
CREATE INDEX ix_task_chat_messages_user_id ON public.task_chat_messages USING btree (user_id);
COMMENT ON TABLE public.task_chat_messages IS '任务聊天消息表';


-- Table: public.tasks
CREATE TABLE public.tasks (
    id integer DEFAULT nextval('tasks_id_seq'::regclass) NOT NULL,
    user_id integer NOT NULL,
    title character varying(200) NOT NULL,
    description text,
    status USER-DEFINED,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    model_name character varying(255),
    small_fast_model_name character varying(255),
    visual_model_name character varying(255),
    compact_model_name character varying(255),
    model_id character varying(255),
    small_fast_model_id character varying(255),
    visual_model_id character varying(255),
    compact_model_id character varying(255),
    agent_id integer,
    agent_type character varying(20),
    agent_config json,
    vibe_mode character varying(20),
    process_description text,
    examples json,
    channel_id integer,
    channel_name character varying(100),
    input_tokens integer,
    output_tokens integer,
    total_tokens integer,
    llm_calls integer,
    token_usage_details json,
    PRIMARY KEY (id)
);
ALTER TABLE public.tasks ADD CONSTRAINT tasks_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);
ALTER TABLE public.tasks ADD CONSTRAINT tasks_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES public.agents(id);
ALTER TABLE public.tasks ADD CONSTRAINT tasks_channel_id_fkey FOREIGN KEY (channel_id) REFERENCES public.user_channels(id);
CREATE INDEX ix_tasks_id ON public.tasks USING btree (id);
COMMENT ON TABLE public.tasks IS '用户任务表';
COMMENT ON COLUMN public.tasks.id IS '任务ID';
COMMENT ON COLUMN public.tasks.user_id IS '用户ID';
COMMENT ON COLUMN public.tasks.title IS '任务标题';
COMMENT ON COLUMN public.tasks.description IS '任务描述';
COMMENT ON COLUMN public.tasks.status IS '任务状态';
COMMENT ON COLUMN public.tasks.created_at IS '创建时间';
COMMENT ON COLUMN public.tasks.updated_at IS '更新时间';
COMMENT ON COLUMN public.tasks.model_name IS '主模型名称';
COMMENT ON COLUMN public.tasks.small_fast_model_name IS '小模型名称';
COMMENT ON COLUMN public.tasks.visual_model_name IS '视觉模型名称';
COMMENT ON COLUMN public.tasks.compact_model_name IS '紧凑模型名称';
COMMENT ON COLUMN public.tasks.model_id IS '主模型ID';
COMMENT ON COLUMN public.tasks.small_fast_model_id IS '小模型ID';
COMMENT ON COLUMN public.tasks.visual_model_id IS '视觉模型ID';
COMMENT ON COLUMN public.tasks.compact_model_id IS '紧凑模型ID';
COMMENT ON COLUMN public.tasks.agent_id IS 'Agent ID';
COMMENT ON COLUMN public.tasks.agent_type IS 'Agent类型';
COMMENT ON COLUMN public.tasks.agent_config IS 'Agent配置';
COMMENT ON COLUMN public.tasks.vibe_mode IS '交互模式(task/process)';
COMMENT ON COLUMN public.tasks.process_description IS '流程描述';
COMMENT ON COLUMN public.tasks.examples IS '示例';
COMMENT ON COLUMN public.tasks.channel_id IS '渠道ID';
COMMENT ON COLUMN public.tasks.channel_name IS '渠道名称';
COMMENT ON COLUMN public.tasks.input_tokens IS '输入token数';
COMMENT ON COLUMN public.tasks.output_tokens IS '输出token数';
COMMENT ON COLUMN public.tasks.total_tokens IS '总token数';
COMMENT ON COLUMN public.tasks.llm_calls IS 'LLM调用次数';
COMMENT ON COLUMN public.tasks.token_usage_details IS 'Token使用详情';


-- Table: public.template_stats
CREATE TABLE public.template_stats (
    id integer DEFAULT nextval('template_stats_id_seq'::regclass) NOT NULL,
    template_id character varying(200) NOT NULL,
    views integer NOT NULL,
    likes integer NOT NULL,
    used_count integer NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    PRIMARY KEY (id)
);
CREATE UNIQUE INDEX ix_template_stats_template_id ON public.template_stats USING btree (template_id);
CREATE INDEX ix_template_stats_id ON public.template_stats USING btree (id);
COMMENT ON TABLE public.template_stats IS '模板使用统计表';


-- Table: public.text2sql_databases
CREATE TABLE public.text2sql_databases (
    id integer DEFAULT nextval('text2sql_databases_id_seq'::regclass) NOT NULL,
    user_id integer NOT NULL,
    name character varying(255) NOT NULL,
    system_short character varying(64) NOT NULL,
    database_name character varying(255),
    env character varying(32) NOT NULL,
    type USER-DEFINED NOT NULL,
    url text NOT NULL,
    read_only boolean NOT NULL,
    status USER-DEFINED NOT NULL,
    table_count integer,
    last_connected_at timestamp with time zone,
    error_message text,
    lifecycle_status character varying(32) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    PRIMARY KEY (id)
);
ALTER TABLE public.text2sql_databases ADD CONSTRAINT text2sql_databases_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);
CREATE INDEX ix_text2sql_databases_lifecycle_status ON public.text2sql_databases USING btree (lifecycle_status);
CREATE INDEX ix_text2sql_databases_env ON public.text2sql_databases USING btree (env);
CREATE INDEX ix_text2sql_databases_id ON public.text2sql_databases USING btree (id);
CREATE INDEX ix_text2sql_databases_system_short ON public.text2sql_databases USING btree (system_short);
CREATE INDEX ix_text2sql_databases_user_id ON public.text2sql_databases USING btree (user_id);
CREATE INDEX ix_text2sql_databases_database_name ON public.text2sql_databases USING btree (database_name);
COMMENT ON TABLE public.text2sql_databases IS 'Text2SQL数据源表';
COMMENT ON COLUMN public.text2sql_databases.id IS '数据源ID';
COMMENT ON COLUMN public.text2sql_databases.user_id IS '用户ID';
COMMENT ON COLUMN public.text2sql_databases.name IS '数据源名称';
COMMENT ON COLUMN public.text2sql_databases.system_short IS '系统简称';
COMMENT ON COLUMN public.text2sql_databases.database_name IS '逻辑数据库名称';
COMMENT ON COLUMN public.text2sql_databases.env IS '环境（如prod/dev）';
COMMENT ON COLUMN public.text2sql_databases.type IS '数据库类型';
COMMENT ON COLUMN public.text2sql_databases.url IS '数据库连接URL';
COMMENT ON COLUMN public.text2sql_databases.read_only IS '是否只读';
COMMENT ON COLUMN public.text2sql_databases.status IS '连接状态（connected/disconnected/error）';
COMMENT ON COLUMN public.text2sql_databases.table_count IS '表数量';
COMMENT ON COLUMN public.text2sql_databases.last_connected_at IS '最后连接时间';
COMMENT ON COLUMN public.text2sql_databases.error_message IS '错误信息';
COMMENT ON COLUMN public.text2sql_databases.lifecycle_status IS '资产生命周期状态（active/archived）';
COMMENT ON COLUMN public.text2sql_databases.created_at IS '创建时间';
COMMENT ON COLUMN public.text2sql_databases.updated_at IS '更新时间';


-- Table: public.tool_configs
CREATE TABLE public.tool_configs (
    id integer DEFAULT nextval('tool_configs_id_seq'::regclass) NOT NULL,
    tool_name character varying(100) NOT NULL,
    tool_type character varying(20) NOT NULL,
    category character varying(50) NOT NULL,
    display_name character varying(100) NOT NULL,
    description text,
    enabled boolean,
    requires_configuration boolean NOT NULL,
    config json,
    dependencies json,
    status character varying(20),
    status_reason character varying(500),
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone,
    PRIMARY KEY (id)
);
CREATE INDEX ix_tool_configs_id ON public.tool_configs USING btree (id);
CREATE UNIQUE INDEX ix_tool_configs_tool_name ON public.tool_configs USING btree (tool_name);
COMMENT ON TABLE public.tool_configs IS '用户工具配置表';


-- Table: public.tool_usage
CREATE TABLE public.tool_usage (
    id integer DEFAULT nextval('tool_usage_id_seq'::regclass) NOT NULL,
    tool_name character varying(100) NOT NULL,
    usage_count integer,
    success_count integer,
    error_count integer,
    last_used_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone,
    PRIMARY KEY (id)
);
CREATE INDEX ix_tool_usage_tool_name ON public.tool_usage USING btree (tool_name);
CREATE INDEX ix_tool_usage_id ON public.tool_usage USING btree (id);
COMMENT ON TABLE public.tool_usage IS '工具使用记录表';


-- Table: public.trace_events
CREATE TABLE public.trace_events (
    id integer DEFAULT nextval('trace_events_id_seq'::regclass) NOT NULL,
    task_id integer NOT NULL,
    build_id character varying(255),
    event_id character varying(255) NOT NULL,
    event_type character varying(100) NOT NULL,
    timestamp timestamp with time zone NOT NULL,
    step_id character varying(255),
    parent_event_id character varying(255),
    data json NOT NULL,
    PRIMARY KEY (id)
);
ALTER TABLE public.trace_events ADD CONSTRAINT trace_events_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.tasks(id);
CREATE INDEX ix_trace_events_id ON public.trace_events USING btree (id);
CREATE INDEX ix_trace_events_build_id ON public.trace_events USING btree (build_id);
COMMENT ON TABLE public.trace_events IS 'Trace事件表';
COMMENT ON COLUMN public.trace_events.id IS '事件ID';
COMMENT ON COLUMN public.trace_events.task_id IS '任务ID';
COMMENT ON COLUMN public.trace_events.build_id IS '构建ID';
COMMENT ON COLUMN public.trace_events.event_id IS '事件UUID';
COMMENT ON COLUMN public.trace_events.event_type IS '事件类型';
COMMENT ON COLUMN public.trace_events.timestamp IS '时间戳';
COMMENT ON COLUMN public.trace_events.step_id IS '步骤ID';
COMMENT ON COLUMN public.trace_events.parent_event_id IS '父事件ID';
COMMENT ON COLUMN public.trace_events.data IS '事件数据';


-- Table: public.uploaded_files
CREATE TABLE public.uploaded_files (
    id integer DEFAULT nextval('uploaded_files_id_seq'::regclass) NOT NULL,
    file_id character varying(36) NOT NULL,
    user_id integer NOT NULL,
    task_id integer,
    filename character varying(512) NOT NULL,
    storage_path character varying(2048) NOT NULL,
    mime_type character varying(255),
    file_size integer NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone,
    PRIMARY KEY (id)
);
ALTER TABLE public.uploaded_files ADD CONSTRAINT uploaded_files_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);
ALTER TABLE public.uploaded_files ADD CONSTRAINT uploaded_files_task_id_fkey FOREIGN KEY (task_id) REFERENCES public.tasks(id);
CREATE UNIQUE INDEX uploaded_files_storage_path_key ON public.uploaded_files USING btree (storage_path);
CREATE INDEX ix_uploaded_files_id ON public.uploaded_files USING btree (id);
CREATE UNIQUE INDEX ix_uploaded_files_file_id ON public.uploaded_files USING btree (file_id);
COMMENT ON TABLE public.uploaded_files IS '用户上传文件表';


-- Table: public.user_channels
CREATE TABLE public.user_channels (
    id integer DEFAULT nextval('user_channels_id_seq'::regclass) NOT NULL,
    user_id integer NOT NULL,
    channel_type character varying(50) NOT NULL,
    channel_name character varying(100) NOT NULL,
    config json NOT NULL,
    is_active boolean NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone,
    PRIMARY KEY (id)
);
ALTER TABLE public.user_channels ADD CONSTRAINT user_channels_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);
CREATE INDEX ix_user_channels_id ON public.user_channels USING btree (id);
COMMENT ON TABLE public.user_channels IS '用户渠道配置表';


-- Table: public.user_default_models
CREATE TABLE public.user_default_models (
    id integer DEFAULT nextval('user_default_models_id_seq'::regclass) NOT NULL,
    user_id integer NOT NULL,
    model_id integer NOT NULL,
    config_type character varying(50) NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone,
    PRIMARY KEY (id)
);
ALTER TABLE public.user_default_models ADD CONSTRAINT user_default_models_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);
ALTER TABLE public.user_default_models ADD CONSTRAINT user_default_models_model_id_fkey FOREIGN KEY (model_id) REFERENCES public.models(id);
CREATE UNIQUE INDEX uq_user_default_model ON public.user_default_models USING btree (user_id, config_type);
CREATE INDEX ix_user_default_models_id ON public.user_default_models USING btree (id);
COMMENT ON TABLE public.user_default_models IS '用户默认模型配置表';
COMMENT ON COLUMN public.user_default_models.id IS '配置ID';
COMMENT ON COLUMN public.user_default_models.user_id IS '用户ID';
COMMENT ON COLUMN public.user_default_models.model_id IS '模型ID';
COMMENT ON COLUMN public.user_default_models.config_type IS '配置类型(general/small_fast/visual/compact/embedding)';
COMMENT ON COLUMN public.user_default_models.created_at IS '创建时间';
COMMENT ON COLUMN public.user_default_models.updated_at IS '更新时间';


-- Table: public.user_mcpservers
CREATE TABLE public.user_mcpservers (
    id integer DEFAULT nextval('user_mcpservers_id_seq'::regclass) NOT NULL,
    user_id integer NOT NULL,
    mcpserver_id integer NOT NULL,
    is_owner boolean NOT NULL,
    can_edit boolean NOT NULL,
    can_delete boolean NOT NULL,
    is_shared boolean NOT NULL,
    is_active boolean NOT NULL,
    is_default boolean NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone,
    PRIMARY KEY (id)
);
ALTER TABLE public.user_mcpservers ADD CONSTRAINT user_mcpservers_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);
ALTER TABLE public.user_mcpservers ADD CONSTRAINT user_mcpservers_mcpserver_id_fkey FOREIGN KEY (mcpserver_id) REFERENCES public.mcp_servers(id);
CREATE UNIQUE INDEX uq_user_mcpservers ON public.user_mcpservers USING btree (user_id, mcpserver_id);
CREATE INDEX ix_user_mcpservers_id ON public.user_mcpservers USING btree (id);
COMMENT ON TABLE public.user_mcpservers IS '用户与MCP服务器关系表';
COMMENT ON COLUMN public.user_mcpservers.id IS '关系ID';
COMMENT ON COLUMN public.user_mcpservers.user_id IS '用户ID';
COMMENT ON COLUMN public.user_mcpservers.mcpserver_id IS 'MCP服务器ID';
COMMENT ON COLUMN public.user_mcpservers.is_owner IS '是否所有者';
COMMENT ON COLUMN public.user_mcpservers.can_edit IS '是否可编辑';
COMMENT ON COLUMN public.user_mcpservers.can_delete IS '是否可删除';
COMMENT ON COLUMN public.user_mcpservers.is_shared IS '是否共享';
COMMENT ON COLUMN public.user_mcpservers.is_active IS '是否启用';
COMMENT ON COLUMN public.user_mcpservers.is_default IS '是否默认';
COMMENT ON COLUMN public.user_mcpservers.created_at IS '创建时间';
COMMENT ON COLUMN public.user_mcpservers.updated_at IS '更新时间';


-- Table: public.user_models
CREATE TABLE public.user_models (
    id integer DEFAULT nextval('user_models_id_seq'::regclass) NOT NULL,
    user_id integer NOT NULL,
    model_id integer NOT NULL,
    is_owner boolean NOT NULL,
    can_edit boolean NOT NULL,
    can_delete boolean NOT NULL,
    is_shared boolean NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone,
    PRIMARY KEY (id)
);
ALTER TABLE public.user_models ADD CONSTRAINT user_models_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);
ALTER TABLE public.user_models ADD CONSTRAINT user_models_model_id_fkey FOREIGN KEY (model_id) REFERENCES public.models(id);
CREATE UNIQUE INDEX uq_user_model ON public.user_models USING btree (user_id, model_id);
CREATE INDEX ix_user_models_id ON public.user_models USING btree (id);
COMMENT ON TABLE public.user_models IS '用户与模型的关系表';
COMMENT ON COLUMN public.user_models.id IS '关系ID';
COMMENT ON COLUMN public.user_models.user_id IS '用户ID';
COMMENT ON COLUMN public.user_models.model_id IS '模型ID';
COMMENT ON COLUMN public.user_models.is_owner IS '是否所有者';
COMMENT ON COLUMN public.user_models.can_edit IS '是否可编辑';
COMMENT ON COLUMN public.user_models.can_delete IS '是否可删除';
COMMENT ON COLUMN public.user_models.is_shared IS '是否共享';
COMMENT ON COLUMN public.user_models.created_at IS '创建时间';
COMMENT ON COLUMN public.user_models.updated_at IS '更新时间';


-- Table: public.user_oauth
CREATE TABLE public.user_oauth (
    id integer DEFAULT nextval('user_oauth_id_seq'::regclass) NOT NULL,
    user_id integer NOT NULL,
    provider character varying(50) NOT NULL,
    access_token character varying NOT NULL,
    refresh_token character varying,
    expires_at timestamp with time zone,
    token_type character varying(50),
    scope character varying,
    provider_user_id character varying,
    email character varying,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone,
    PRIMARY KEY (id)
);
ALTER TABLE public.user_oauth ADD CONSTRAINT user_oauth_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);
CREATE UNIQUE INDEX uq_user_provider_account ON public.user_oauth USING btree (user_id, provider, provider_user_id);
CREATE INDEX ix_user_oauth_id ON public.user_oauth USING btree (id);
COMMENT ON TABLE public.user_oauth IS '用户OAuth账号绑定表';


-- Table: public.user_system_roles
CREATE TABLE public.user_system_roles (
    id integer DEFAULT nextval('user_system_roles_id_seq'::regclass) NOT NULL,
    user_id integer NOT NULL,
    system_short character varying(64) NOT NULL,
    role character varying(32) NOT NULL,
    granted_by integer NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    PRIMARY KEY (id)
);
ALTER TABLE public.user_system_roles ADD CONSTRAINT user_system_roles_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);
ALTER TABLE public.user_system_roles ADD CONSTRAINT user_system_roles_system_short_fkey FOREIGN KEY (system_short) REFERENCES public.system_registry(system_short);
CREATE UNIQUE INDEX uq_user_system_role ON public.user_system_roles USING btree (user_id, system_short);
CREATE INDEX ix_user_system_roles_role ON public.user_system_roles USING btree (role);
CREATE INDEX ix_user_system_roles_granted_by ON public.user_system_roles USING btree (granted_by);
CREATE INDEX ix_user_system_roles_id ON public.user_system_roles USING btree (id);
CREATE INDEX ix_user_system_roles_system_short ON public.user_system_roles USING btree (system_short);
CREATE INDEX ix_user_system_roles_user_id ON public.user_system_roles USING btree (user_id);
COMMENT ON TABLE public.user_system_roles IS '用户系统角色表';
COMMENT ON COLUMN public.user_system_roles.id IS '角色ID';
COMMENT ON COLUMN public.user_system_roles.user_id IS '用户ID';
COMMENT ON COLUMN public.user_system_roles.system_short IS '系统简称';
COMMENT ON COLUMN public.user_system_roles.role IS '角色(member/system_admin)';
COMMENT ON COLUMN public.user_system_roles.granted_by IS '授权人ID';
COMMENT ON COLUMN public.user_system_roles.created_at IS '创建时间';


-- Table: public.user_tool_configs
CREATE TABLE public.user_tool_configs (
    id integer DEFAULT nextval('user_tool_configs_id_seq'::regclass) NOT NULL,
    user_id integer NOT NULL,
    tool_name character varying(100) NOT NULL,
    config json,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone,
    PRIMARY KEY (id)
);
ALTER TABLE public.user_tool_configs ADD CONSTRAINT user_tool_configs_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id);
CREATE UNIQUE INDEX uq_user_tool_config ON public.user_tool_configs USING btree (user_id, tool_name);
CREATE INDEX ix_user_tool_configs_user_id ON public.user_tool_configs USING btree (user_id);
CREATE INDEX ix_user_tool_configs_id ON public.user_tool_configs USING btree (id);
CREATE INDEX ix_user_tool_configs_tool_name ON public.user_tool_configs USING btree (tool_name);


-- Table: public.users
CREATE TABLE public.users (
    id integer DEFAULT nextval('users_id_seq'::regclass) NOT NULL,
    username character varying(50) NOT NULL,
    password_hash character varying(255) NOT NULL,
    is_admin boolean NOT NULL,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    refresh_token character varying(255),
    refresh_token_expires_at timestamp with time zone,
    PRIMARY KEY (id)
);
CREATE INDEX ix_users_id ON public.users USING btree (id);
CREATE UNIQUE INDEX ix_users_username ON public.users USING btree (username);
COMMENT ON TABLE public.users IS '平台用户表';
COMMENT ON COLUMN public.users.id IS '用户ID';
COMMENT ON COLUMN public.users.username IS '用户名';
COMMENT ON COLUMN public.users.password_hash IS '密码哈希';
COMMENT ON COLUMN public.users.is_admin IS '是否管理员';
COMMENT ON COLUMN public.users.created_at IS '创建时间';
COMMENT ON COLUMN public.users.updated_at IS '更新时间';
COMMENT ON COLUMN public.users.refresh_token IS '刷新令牌';
COMMENT ON COLUMN public.users.refresh_token_expires_at IS '刷新令牌过期时间';


-- Table: public.vanna_ask_runs
CREATE TABLE public.vanna_ask_runs (
    id integer DEFAULT nextval('vanna_ask_runs_id_seq'::regclass) NOT NULL,
    kb_id integer NOT NULL,
    datasource_id integer NOT NULL,
    system_short character varying(64) NOT NULL,
    env character varying(32) NOT NULL,
    task_id integer,
    question_text text NOT NULL,
    rewritten_question text,
    retrieval_snapshot_json json,
    prompt_snapshot_json json,
    generated_sql text,
    sql_confidence double precision,
    execution_mode character varying(32),
    execution_status character varying(32) NOT NULL,
    execution_result_json json,
    approval_status character varying(32),
    auto_train_entry_id integer,
    create_user_id integer NOT NULL,
    create_user_name character varying(255),
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    PRIMARY KEY (id)
);
ALTER TABLE public.vanna_ask_runs ADD CONSTRAINT vanna_ask_runs_kb_id_fkey FOREIGN KEY (kb_id) REFERENCES public.vanna_knowledge_bases(id);
ALTER TABLE public.vanna_ask_runs ADD CONSTRAINT vanna_ask_runs_datasource_id_fkey FOREIGN KEY (datasource_id) REFERENCES public.text2sql_databases(id);
ALTER TABLE public.vanna_ask_runs ADD CONSTRAINT vanna_ask_runs_auto_train_entry_id_fkey FOREIGN KEY (auto_train_entry_id) REFERENCES public.vanna_training_entries(id);
CREATE INDEX ix_vanna_ask_runs_env ON public.vanna_ask_runs USING btree (env);
CREATE INDEX ix_vanna_ask_runs_create_user_id ON public.vanna_ask_runs USING btree (create_user_id);
CREATE INDEX ix_vanna_ask_runs_approval_status ON public.vanna_ask_runs USING btree (approval_status);
CREATE INDEX ix_vanna_ask_runs_datasource_id ON public.vanna_ask_runs USING btree (datasource_id);
CREATE INDEX ix_vanna_ask_runs_id ON public.vanna_ask_runs USING btree (id);
CREATE INDEX ix_vanna_ask_runs_task_id ON public.vanna_ask_runs USING btree (task_id);
CREATE INDEX ix_vanna_ask_runs_execution_mode ON public.vanna_ask_runs USING btree (execution_mode);
CREATE INDEX ix_vanna_ask_runs_auto_train_entry_id ON public.vanna_ask_runs USING btree (auto_train_entry_id);
CREATE INDEX ix_vanna_ask_runs_kb_id ON public.vanna_ask_runs USING btree (kb_id);
CREATE INDEX ix_vanna_ask_runs_execution_status ON public.vanna_ask_runs USING btree (execution_status);
CREATE INDEX ix_vanna_ask_runs_system_short ON public.vanna_ask_runs USING btree (system_short);
COMMENT ON TABLE public.vanna_ask_runs IS 'Ask运行记录表';
COMMENT ON COLUMN public.vanna_ask_runs.id IS 'Ask运行ID';
COMMENT ON COLUMN public.vanna_ask_runs.kb_id IS '知识库ID';
COMMENT ON COLUMN public.vanna_ask_runs.datasource_id IS '数据源ID';
COMMENT ON COLUMN public.vanna_ask_runs.system_short IS '系统简称';
COMMENT ON COLUMN public.vanna_ask_runs.env IS '环境（如prod/dev）';
COMMENT ON COLUMN public.vanna_ask_runs.task_id IS '任务ID';
COMMENT ON COLUMN public.vanna_ask_runs.question_text IS '问题文本';
COMMENT ON COLUMN public.vanna_ask_runs.rewritten_question IS '重写后的问题';
COMMENT ON COLUMN public.vanna_ask_runs.retrieval_snapshot_json IS '检索快照（JSON格式）';
COMMENT ON COLUMN public.vanna_ask_runs.prompt_snapshot_json IS '提示快照（JSON格式）';
COMMENT ON COLUMN public.vanna_ask_runs.generated_sql IS '生成的SQL';
COMMENT ON COLUMN public.vanna_ask_runs.sql_confidence IS 'SQL置信度';
COMMENT ON COLUMN public.vanna_ask_runs.execution_mode IS '执行模式（dry_run/execute）';
COMMENT ON COLUMN public.vanna_ask_runs.execution_status IS '执行状态（generated/executed/failed/waiting_approval）';
COMMENT ON COLUMN public.vanna_ask_runs.execution_result_json IS '执行结果（JSON格式）';
COMMENT ON COLUMN public.vanna_ask_runs.approval_status IS '审批状态';
COMMENT ON COLUMN public.vanna_ask_runs.auto_train_entry_id IS '自动训练条目ID';
COMMENT ON COLUMN public.vanna_ask_runs.create_user_id IS '创建用户ID';
COMMENT ON COLUMN public.vanna_ask_runs.create_user_name IS '创建用户名';
COMMENT ON COLUMN public.vanna_ask_runs.created_at IS '创建时间';
COMMENT ON COLUMN public.vanna_ask_runs.updated_at IS '更新时间';


-- Table: public.vanna_embedding_chunks
CREATE TABLE public.vanna_embedding_chunks (
    id integer DEFAULT nextval('vanna_embedding_chunks_id_seq'::regclass) NOT NULL,
    kb_id integer NOT NULL,
    datasource_id integer NOT NULL,
    entry_id integer NOT NULL,
    system_short character varying(64) NOT NULL,
    env character varying(32) NOT NULL,
    source_table character varying(64),
    source_row_id integer,
    chunk_type character varying(32) NOT NULL,
    chunk_order integer NOT NULL,
    chunk_text text NOT NULL,
    embedding_text text,
    embedding_model character varying(128),
    embedding_dim integer,
    embedding_vector USER-DEFINED,
    distance_metric character varying(16),
    token_count_estimate integer,
    lifecycle_status character varying(32) NOT NULL,
    metadata_json json,
    chunk_hash character varying(64),
    created_at timestamp with time zone NOT NULL,
    PRIMARY KEY (id)
);
ALTER TABLE public.vanna_embedding_chunks ADD CONSTRAINT vanna_embedding_chunks_kb_id_fkey FOREIGN KEY (kb_id) REFERENCES public.vanna_knowledge_bases(id);
ALTER TABLE public.vanna_embedding_chunks ADD CONSTRAINT vanna_embedding_chunks_datasource_id_fkey FOREIGN KEY (datasource_id) REFERENCES public.text2sql_databases(id);
ALTER TABLE public.vanna_embedding_chunks ADD CONSTRAINT vanna_embedding_chunks_entry_id_fkey FOREIGN KEY (entry_id) REFERENCES public.vanna_training_entries(id);
CREATE INDEX ix_vanna_embedding_chunks_kb_id ON public.vanna_embedding_chunks USING btree (kb_id);
CREATE INDEX ix_vanna_embedding_chunks_system_short ON public.vanna_embedding_chunks USING btree (system_short);
CREATE INDEX ix_vanna_embedding_chunks_source_row_id ON public.vanna_embedding_chunks USING btree (source_row_id);
CREATE INDEX ix_vanna_embedding_chunks_embedding_model ON public.vanna_embedding_chunks USING btree (embedding_model);
CREATE INDEX ix_vanna_embedding_chunks_chunk_hash ON public.vanna_embedding_chunks USING btree (chunk_hash);
CREATE INDEX ix_vanna_embedding_chunks_entry_id ON public.vanna_embedding_chunks USING btree (entry_id);
CREATE INDEX ix_vanna_embedding_chunks_env ON public.vanna_embedding_chunks USING btree (env);
CREATE INDEX ix_vanna_embedding_chunks_chunk_type ON public.vanna_embedding_chunks USING btree (chunk_type);
CREATE INDEX ix_vanna_embedding_chunks_source_table ON public.vanna_embedding_chunks USING btree (source_table);
CREATE INDEX ix_vanna_embedding_chunks_datasource_id ON public.vanna_embedding_chunks USING btree (datasource_id);
CREATE INDEX ix_vanna_embedding_chunks_id ON public.vanna_embedding_chunks USING btree (id);
CREATE INDEX ix_vanna_embedding_chunks_kb_chunk_lifecycle_model ON public.vanna_embedding_chunks USING btree (kb_id, chunk_type, lifecycle_status, embedding_model);
CREATE INDEX ix_vanna_embedding_chunks_lifecycle_status ON public.vanna_embedding_chunks USING btree (lifecycle_status);
CREATE INDEX ix_vanna_embedding_chunks_entry_chunk_type ON public.vanna_embedding_chunks USING btree (entry_id, chunk_type);
COMMENT ON TABLE public.vanna_embedding_chunks IS '向量检索切片表';
COMMENT ON COLUMN public.vanna_embedding_chunks.id IS '切片ID';
COMMENT ON COLUMN public.vanna_embedding_chunks.kb_id IS '知识库ID';
COMMENT ON COLUMN public.vanna_embedding_chunks.datasource_id IS '数据源ID';
COMMENT ON COLUMN public.vanna_embedding_chunks.entry_id IS '训练条目ID';
COMMENT ON COLUMN public.vanna_embedding_chunks.system_short IS '系统简称';
COMMENT ON COLUMN public.vanna_embedding_chunks.env IS '环境（如prod/dev）';
COMMENT ON COLUMN public.vanna_embedding_chunks.source_table IS '来源表';
COMMENT ON COLUMN public.vanna_embedding_chunks.source_row_id IS '来源行ID';
COMMENT ON COLUMN public.vanna_embedding_chunks.chunk_type IS '切片类型（question_sql/schema_summary/documentation）';
COMMENT ON COLUMN public.vanna_embedding_chunks.chunk_order IS '切片顺序';
COMMENT ON COLUMN public.vanna_embedding_chunks.chunk_text IS '切片文本';
COMMENT ON COLUMN public.vanna_embedding_chunks.embedding_text IS '嵌入文本';
COMMENT ON COLUMN public.vanna_embedding_chunks.embedding_model IS '嵌入模型名称';
COMMENT ON COLUMN public.vanna_embedding_chunks.embedding_dim IS '嵌入维度';
COMMENT ON COLUMN public.vanna_embedding_chunks.embedding_vector IS '嵌入向量';
COMMENT ON COLUMN public.vanna_embedding_chunks.distance_metric IS '距离度量（如cosine/euclidean）';
COMMENT ON COLUMN public.vanna_embedding_chunks.token_count_estimate IS 'Token数估计';
COMMENT ON COLUMN public.vanna_embedding_chunks.lifecycle_status IS '生命周期状态（candidate/published/archived）';
COMMENT ON COLUMN public.vanna_embedding_chunks.metadata_json IS '元数据（JSON格式）';
COMMENT ON COLUMN public.vanna_embedding_chunks.chunk_hash IS '切片哈希';
COMMENT ON COLUMN public.vanna_embedding_chunks.created_at IS '创建时间';


-- Table: public.vanna_knowledge_bases
CREATE TABLE public.vanna_knowledge_bases (
    id integer DEFAULT nextval('vanna_knowledge_bases_id_seq'::regclass) NOT NULL,
    kb_code character varying(255) NOT NULL,
    name character varying(255) NOT NULL,
    description text,
    owner_user_id integer NOT NULL,
    owner_user_name character varying(255),
    datasource_id integer NOT NULL,
    datasource_name character varying(255),
    system_short character varying(64) NOT NULL,
    database_name character varying(255),
    env character varying(32) NOT NULL,
    db_type character varying(64),
    dialect character varying(64),
    status character varying(32) NOT NULL,
    default_top_k_sql integer,
    default_top_k_schema integer,
    default_top_k_doc integer,
    embedding_model character varying(128),
    llm_model character varying(128),
    last_train_at timestamp with time zone,
    last_ask_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    PRIMARY KEY (id)
);
ALTER TABLE public.vanna_knowledge_bases ADD CONSTRAINT vanna_knowledge_bases_datasource_id_fkey FOREIGN KEY (datasource_id) REFERENCES public.text2sql_databases(id);
CREATE UNIQUE INDEX ix_vanna_knowledge_bases_kb_code ON public.vanna_knowledge_bases USING btree (kb_code);
CREATE INDEX ix_vanna_knowledge_bases_datasource_id ON public.vanna_knowledge_bases USING btree (datasource_id);
CREATE INDEX ix_vanna_knowledge_bases_database_name ON public.vanna_knowledge_bases USING btree (database_name);
CREATE INDEX ix_vanna_knowledge_bases_dialect ON public.vanna_knowledge_bases USING btree (dialect);
CREATE INDEX ix_vanna_knowledge_bases_status ON public.vanna_knowledge_bases USING btree (status);
CREATE INDEX ix_vanna_knowledge_bases_env ON public.vanna_knowledge_bases USING btree (env);
CREATE INDEX ix_vanna_knowledge_bases_db_type ON public.vanna_knowledge_bases USING btree (db_type);
CREATE INDEX ix_vanna_knowledge_bases_owner_user_id ON public.vanna_knowledge_bases USING btree (owner_user_id);
CREATE INDEX ix_vanna_knowledge_bases_system_short ON public.vanna_knowledge_bases USING btree (system_short);
CREATE INDEX ix_vanna_knowledge_bases_id ON public.vanna_knowledge_bases USING btree (id);
COMMENT ON TABLE public.vanna_knowledge_bases IS 'Vanna知识库表';
COMMENT ON COLUMN public.vanna_knowledge_bases.id IS '知识库ID';
COMMENT ON COLUMN public.vanna_knowledge_bases.kb_code IS '知识库唯一编码';
COMMENT ON COLUMN public.vanna_knowledge_bases.name IS '知识库名称';
COMMENT ON COLUMN public.vanna_knowledge_bases.description IS '知识库描述';
COMMENT ON COLUMN public.vanna_knowledge_bases.owner_user_id IS '所有者用户ID';
COMMENT ON COLUMN public.vanna_knowledge_bases.owner_user_name IS '所有者用户名';
COMMENT ON COLUMN public.vanna_knowledge_bases.datasource_id IS '关联的数据源ID';
COMMENT ON COLUMN public.vanna_knowledge_bases.datasource_name IS '数据源名称';
COMMENT ON COLUMN public.vanna_knowledge_bases.system_short IS '系统简称';
COMMENT ON COLUMN public.vanna_knowledge_bases.database_name IS '逻辑数据库名称';
COMMENT ON COLUMN public.vanna_knowledge_bases.env IS '环境（如prod/dev）';
COMMENT ON COLUMN public.vanna_knowledge_bases.db_type IS '数据库类型';
COMMENT ON COLUMN public.vanna_knowledge_bases.dialect IS 'SQL方言';
COMMENT ON COLUMN public.vanna_knowledge_bases.status IS '知识库状态（draft/active/archived）';
COMMENT ON COLUMN public.vanna_knowledge_bases.default_top_k_sql IS '默认SQL检索TopK';
COMMENT ON COLUMN public.vanna_knowledge_bases.default_top_k_schema IS '默认Schema检索TopK';
COMMENT ON COLUMN public.vanna_knowledge_bases.default_top_k_doc IS '默认文档检索TopK';
COMMENT ON COLUMN public.vanna_knowledge_bases.embedding_model IS '嵌入模型名称';
COMMENT ON COLUMN public.vanna_knowledge_bases.llm_model IS 'LLM模型名称';
COMMENT ON COLUMN public.vanna_knowledge_bases.last_train_at IS '最后训练时间';
COMMENT ON COLUMN public.vanna_knowledge_bases.last_ask_at IS '最后查询时间';
COMMENT ON COLUMN public.vanna_knowledge_bases.created_at IS '创建时间';
COMMENT ON COLUMN public.vanna_knowledge_bases.updated_at IS '更新时间';


-- Table: public.vanna_schema_column_annotations
CREATE TABLE public.vanna_schema_column_annotations (
    id integer DEFAULT nextval('vanna_schema_column_annotations_id_seq'::regclass) NOT NULL,
    kb_id integer NOT NULL,
    datasource_id integer NOT NULL,
    system_short character varying(64) NOT NULL,
    env character varying(32) NOT NULL,
    schema_name character varying(255) NOT NULL,
    table_name character varying(255) NOT NULL,
    column_name character varying(255) NOT NULL,
    business_description text,
    comment_override text,
    default_value_override text,
    allowed_values_override_json json,
    sample_values_override_json json,
    update_source character varying(32) NOT NULL,
    create_user_id integer NOT NULL,
    create_user_name character varying(255),
    updated_by_user_id integer NOT NULL,
    updated_by_user_name character varying(255),
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    PRIMARY KEY (id)
);
ALTER TABLE public.vanna_schema_column_annotations ADD CONSTRAINT vanna_schema_column_annotations_kb_id_fkey FOREIGN KEY (kb_id) REFERENCES public.vanna_knowledge_bases(id);
ALTER TABLE public.vanna_schema_column_annotations ADD CONSTRAINT vanna_schema_column_annotations_datasource_id_fkey FOREIGN KEY (datasource_id) REFERENCES public.text2sql_databases(id);
CREATE UNIQUE INDEX uq_vanna_schema_column_annotation_key ON public.vanna_schema_column_annotations USING btree (kb_id, schema_name, table_name, column_name);
CREATE INDEX ix_vanna_schema_column_annotations_env ON public.vanna_schema_column_annotations USING btree (env);
CREATE INDEX ix_vanna_schema_column_annotations_kb_table ON public.vanna_schema_column_annotations USING btree (kb_id, schema_name, table_name);
CREATE INDEX ix_vanna_schema_column_annotations_datasource_id ON public.vanna_schema_column_annotations USING btree (datasource_id);
CREATE INDEX ix_vanna_schema_column_annotations_id ON public.vanna_schema_column_annotations USING btree (id);
CREATE INDEX ix_vanna_schema_column_annotations_updated_by_user_id ON public.vanna_schema_column_annotations USING btree (updated_by_user_id);
CREATE INDEX ix_vanna_schema_column_annotations_kb_id ON public.vanna_schema_column_annotations USING btree (kb_id);
CREATE INDEX ix_vanna_schema_column_annotations_table_name ON public.vanna_schema_column_annotations USING btree (table_name);
CREATE INDEX ix_vanna_schema_column_annotations_system_short ON public.vanna_schema_column_annotations USING btree (system_short);
CREATE INDEX ix_vanna_schema_column_annotations_update_source ON public.vanna_schema_column_annotations USING btree (update_source);
CREATE INDEX ix_vanna_schema_column_annotations_column_name ON public.vanna_schema_column_annotations USING btree (column_name);
CREATE INDEX ix_vanna_schema_column_annotations_create_user_id ON public.vanna_schema_column_annotations USING btree (create_user_id);
COMMENT ON TABLE public.vanna_schema_column_annotations IS '列注释表';
COMMENT ON COLUMN public.vanna_schema_column_annotations.id IS '字段注释ID';
COMMENT ON COLUMN public.vanna_schema_column_annotations.kb_id IS '知识库ID';
COMMENT ON COLUMN public.vanna_schema_column_annotations.datasource_id IS '数据源ID';
COMMENT ON COLUMN public.vanna_schema_column_annotations.system_short IS '系统简称';
COMMENT ON COLUMN public.vanna_schema_column_annotations.env IS '环境（如prod/dev）';
COMMENT ON COLUMN public.vanna_schema_column_annotations.schema_name IS 'Schema名称，空字符串表示默认schema';
COMMENT ON COLUMN public.vanna_schema_column_annotations.table_name IS '表名称';
COMMENT ON COLUMN public.vanna_schema_column_annotations.column_name IS '字段名称';
COMMENT ON COLUMN public.vanna_schema_column_annotations.business_description IS '业务说明';
COMMENT ON COLUMN public.vanna_schema_column_annotations.comment_override IS '字段注释覆写';
COMMENT ON COLUMN public.vanna_schema_column_annotations.default_value_override IS '默认值覆写';
COMMENT ON COLUMN public.vanna_schema_column_annotations.allowed_values_override_json IS '取值范围覆写（JSON格式）';
COMMENT ON COLUMN public.vanna_schema_column_annotations.sample_values_override_json IS '示例值覆写（JSON格式）';
COMMENT ON COLUMN public.vanna_schema_column_annotations.update_source IS '更新来源（manual/ai_suggest/imported）';
COMMENT ON COLUMN public.vanna_schema_column_annotations.create_user_id IS '创建用户ID';
COMMENT ON COLUMN public.vanna_schema_column_annotations.create_user_name IS '创建用户名';
COMMENT ON COLUMN public.vanna_schema_column_annotations.updated_by_user_id IS '最后更新用户ID';
COMMENT ON COLUMN public.vanna_schema_column_annotations.updated_by_user_name IS '最后更新用户名';
COMMENT ON COLUMN public.vanna_schema_column_annotations.created_at IS '创建时间';
COMMENT ON COLUMN public.vanna_schema_column_annotations.updated_at IS '更新时间';


-- Table: public.vanna_schema_columns
CREATE TABLE public.vanna_schema_columns (
    id integer DEFAULT nextval('vanna_schema_columns_id_seq'::regclass) NOT NULL,
    table_id integer NOT NULL,
    kb_id integer NOT NULL,
    datasource_id integer NOT NULL,
    system_short character varying(64) NOT NULL,
    env character varying(32) NOT NULL,
    schema_name character varying(255),
    table_name character varying(255) NOT NULL,
    column_name character varying(255) NOT NULL,
    ordinal_position integer,
    data_type character varying(128),
    udt_name character varying(128),
    is_nullable boolean,
    default_raw text,
    default_kind character varying(32),
    column_comment text,
    is_primary_key boolean,
    is_foreign_key boolean,
    foreign_table_name character varying(255),
    foreign_column_name character varying(255),
    is_generated boolean,
    generation_expression text,
    value_source_kind character varying(32),
    allowed_values_json json,
    sample_values_json json,
    stats_json json,
    semantic_tags_json json,
    content_hash character varying(64),
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    PRIMARY KEY (id)
);
ALTER TABLE public.vanna_schema_columns ADD CONSTRAINT vanna_schema_columns_table_id_fkey FOREIGN KEY (table_id) REFERENCES public.vanna_schema_tables(id);
ALTER TABLE public.vanna_schema_columns ADD CONSTRAINT vanna_schema_columns_kb_id_fkey FOREIGN KEY (kb_id) REFERENCES public.vanna_knowledge_bases(id);
ALTER TABLE public.vanna_schema_columns ADD CONSTRAINT vanna_schema_columns_datasource_id_fkey FOREIGN KEY (datasource_id) REFERENCES public.text2sql_databases(id);
CREATE INDEX ix_vanna_schema_columns_system_short ON public.vanna_schema_columns USING btree (system_short);
CREATE INDEX ix_vanna_schema_columns_table_name ON public.vanna_schema_columns USING btree (table_name);
CREATE INDEX ix_vanna_schema_columns_content_hash ON public.vanna_schema_columns USING btree (content_hash);
CREATE INDEX ix_vanna_schema_columns_default_kind ON public.vanna_schema_columns USING btree (default_kind);
CREATE INDEX ix_vanna_schema_columns_value_source_kind ON public.vanna_schema_columns USING btree (value_source_kind);
CREATE INDEX ix_vanna_schema_columns_datasource_id ON public.vanna_schema_columns USING btree (datasource_id);
CREATE INDEX ix_vanna_schema_columns_env ON public.vanna_schema_columns USING btree (env);
CREATE INDEX ix_vanna_schema_columns_column_name ON public.vanna_schema_columns USING btree (column_name);
CREATE INDEX ix_vanna_schema_columns_id ON public.vanna_schema_columns USING btree (id);
CREATE INDEX ix_vanna_schema_columns_schema_name ON public.vanna_schema_columns USING btree (schema_name);
CREATE INDEX ix_vanna_schema_columns_kb_id ON public.vanna_schema_columns USING btree (kb_id);
CREATE INDEX ix_vanna_schema_columns_table_id ON public.vanna_schema_columns USING btree (table_id);
COMMENT ON TABLE public.vanna_schema_columns IS 'Schema列结构快照表';
COMMENT ON COLUMN public.vanna_schema_columns.id IS '字段结构ID';
COMMENT ON COLUMN public.vanna_schema_columns.table_id IS '表结构ID';
COMMENT ON COLUMN public.vanna_schema_columns.kb_id IS '知识库ID';
COMMENT ON COLUMN public.vanna_schema_columns.datasource_id IS '数据源ID';
COMMENT ON COLUMN public.vanna_schema_columns.system_short IS '系统简称';
COMMENT ON COLUMN public.vanna_schema_columns.env IS '环境（如prod/dev）';
COMMENT ON COLUMN public.vanna_schema_columns.schema_name IS 'Schema名称';
COMMENT ON COLUMN public.vanna_schema_columns.table_name IS '表名称';
COMMENT ON COLUMN public.vanna_schema_columns.column_name IS '字段名称';
COMMENT ON COLUMN public.vanna_schema_columns.ordinal_position IS '字段位置';
COMMENT ON COLUMN public.vanna_schema_columns.data_type IS '数据类型';
COMMENT ON COLUMN public.vanna_schema_columns.udt_name IS '用户定义类型名称';
COMMENT ON COLUMN public.vanna_schema_columns.is_nullable IS '是否可空';
COMMENT ON COLUMN public.vanna_schema_columns.default_raw IS '默认值（原始）';
COMMENT ON COLUMN public.vanna_schema_columns.default_kind IS '默认值类型';
COMMENT ON COLUMN public.vanna_schema_columns.column_comment IS '字段注释';
COMMENT ON COLUMN public.vanna_schema_columns.is_primary_key IS '是否主键';
COMMENT ON COLUMN public.vanna_schema_columns.is_foreign_key IS '是否外键';
COMMENT ON COLUMN public.vanna_schema_columns.foreign_table_name IS '外键表名称';
COMMENT ON COLUMN public.vanna_schema_columns.foreign_column_name IS '外键字段名称';
COMMENT ON COLUMN public.vanna_schema_columns.is_generated IS '是否生成列';
COMMENT ON COLUMN public.vanna_schema_columns.generation_expression IS '生成表达式';
COMMENT ON COLUMN public.vanna_schema_columns.value_source_kind IS '值来源类型';
COMMENT ON COLUMN public.vanna_schema_columns.allowed_values_json IS '允许值列表（JSON格式）';
COMMENT ON COLUMN public.vanna_schema_columns.sample_values_json IS '示例值列表（JSON格式）';
COMMENT ON COLUMN public.vanna_schema_columns.stats_json IS '统计信息（JSON格式）';
COMMENT ON COLUMN public.vanna_schema_columns.semantic_tags_json IS '语义标签（JSON格式）';
COMMENT ON COLUMN public.vanna_schema_columns.content_hash IS '内容哈希';
COMMENT ON COLUMN public.vanna_schema_columns.created_at IS '创建时间';
COMMENT ON COLUMN public.vanna_schema_columns.updated_at IS '更新时间';


-- Table: public.vanna_schema_harvest_jobs
CREATE TABLE public.vanna_schema_harvest_jobs (
    id integer DEFAULT nextval('vanna_schema_harvest_jobs_id_seq'::regclass) NOT NULL,
    kb_id integer NOT NULL,
    datasource_id integer NOT NULL,
    system_short character varying(64) NOT NULL,
    env character varying(32) NOT NULL,
    status character varying(32) NOT NULL,
    harvest_scope character varying(32) NOT NULL,
    schema_names_json json,
    table_names_json json,
    request_payload_json json,
    result_payload_json json,
    error_message text,
    create_user_id integer NOT NULL,
    create_user_name character varying(255),
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    PRIMARY KEY (id)
);
ALTER TABLE public.vanna_schema_harvest_jobs ADD CONSTRAINT vanna_schema_harvest_jobs_kb_id_fkey FOREIGN KEY (kb_id) REFERENCES public.vanna_knowledge_bases(id);
ALTER TABLE public.vanna_schema_harvest_jobs ADD CONSTRAINT vanna_schema_harvest_jobs_datasource_id_fkey FOREIGN KEY (datasource_id) REFERENCES public.text2sql_databases(id);
CREATE INDEX ix_vanna_schema_harvest_jobs_datasource_id ON public.vanna_schema_harvest_jobs USING btree (datasource_id);
CREATE INDEX ix_vanna_schema_harvest_jobs_env ON public.vanna_schema_harvest_jobs USING btree (env);
CREATE INDEX ix_vanna_schema_harvest_jobs_kb_id ON public.vanna_schema_harvest_jobs USING btree (kb_id);
CREATE INDEX ix_vanna_schema_harvest_jobs_create_user_id ON public.vanna_schema_harvest_jobs USING btree (create_user_id);
CREATE INDEX ix_vanna_schema_harvest_jobs_status ON public.vanna_schema_harvest_jobs USING btree (status);
CREATE INDEX ix_vanna_schema_harvest_jobs_system_short ON public.vanna_schema_harvest_jobs USING btree (system_short);
CREATE INDEX ix_vanna_schema_harvest_jobs_id ON public.vanna_schema_harvest_jobs USING btree (id);
COMMENT ON TABLE public.vanna_schema_harvest_jobs IS 'Schema采集任务表';
COMMENT ON COLUMN public.vanna_schema_harvest_jobs.id IS '采集任务ID';
COMMENT ON COLUMN public.vanna_schema_harvest_jobs.kb_id IS '知识库ID';
COMMENT ON COLUMN public.vanna_schema_harvest_jobs.datasource_id IS '数据源ID';
COMMENT ON COLUMN public.vanna_schema_harvest_jobs.system_short IS '系统简称';
COMMENT ON COLUMN public.vanna_schema_harvest_jobs.env IS '环境（如prod/dev）';
COMMENT ON COLUMN public.vanna_schema_harvest_jobs.status IS '任务状态（running/completed/failed）';
COMMENT ON COLUMN public.vanna_schema_harvest_jobs.harvest_scope IS '采集范围（all/custom）';
COMMENT ON COLUMN public.vanna_schema_harvest_jobs.schema_names_json IS 'Schema名称列表（JSON格式）';
COMMENT ON COLUMN public.vanna_schema_harvest_jobs.table_names_json IS '表名称列表（JSON格式）';
COMMENT ON COLUMN public.vanna_schema_harvest_jobs.request_payload_json IS '请求参数（JSON格式）';
COMMENT ON COLUMN public.vanna_schema_harvest_jobs.result_payload_json IS '采集结果（JSON格式）';
COMMENT ON COLUMN public.vanna_schema_harvest_jobs.error_message IS '错误信息';
COMMENT ON COLUMN public.vanna_schema_harvest_jobs.create_user_id IS '创建用户ID';
COMMENT ON COLUMN public.vanna_schema_harvest_jobs.create_user_name IS '创建用户名';
COMMENT ON COLUMN public.vanna_schema_harvest_jobs.started_at IS '开始时间';
COMMENT ON COLUMN public.vanna_schema_harvest_jobs.completed_at IS '完成时间';
COMMENT ON COLUMN public.vanna_schema_harvest_jobs.created_at IS '创建时间';
COMMENT ON COLUMN public.vanna_schema_harvest_jobs.updated_at IS '更新时间';


-- Table: public.vanna_schema_tables
CREATE TABLE public.vanna_schema_tables (
    id integer DEFAULT nextval('vanna_schema_tables_id_seq'::regclass) NOT NULL,
    kb_id integer NOT NULL,
    datasource_id integer NOT NULL,
    harvest_job_id integer NOT NULL,
    system_short character varying(64) NOT NULL,
    env character varying(32) NOT NULL,
    catalog_name character varying(255),
    schema_name character varying(255),
    table_name character varying(255) NOT NULL,
    table_type character varying(64),
    table_comment text,
    table_ddl text,
    primary_key_json json,
    foreign_keys_json json,
    indexes_json json,
    constraints_json json,
    row_count_estimate integer,
    content_hash character varying(64),
    status character varying(32) NOT NULL,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    PRIMARY KEY (id)
);
ALTER TABLE public.vanna_schema_tables ADD CONSTRAINT vanna_schema_tables_kb_id_fkey FOREIGN KEY (kb_id) REFERENCES public.vanna_knowledge_bases(id);
ALTER TABLE public.vanna_schema_tables ADD CONSTRAINT vanna_schema_tables_datasource_id_fkey FOREIGN KEY (datasource_id) REFERENCES public.text2sql_databases(id);
ALTER TABLE public.vanna_schema_tables ADD CONSTRAINT vanna_schema_tables_harvest_job_id_fkey FOREIGN KEY (harvest_job_id) REFERENCES public.vanna_schema_harvest_jobs(id);
CREATE INDEX ix_vanna_schema_tables_harvest_job_id ON public.vanna_schema_tables USING btree (harvest_job_id);
CREATE INDEX ix_vanna_schema_tables_env ON public.vanna_schema_tables USING btree (env);
CREATE INDEX ix_vanna_schema_tables_id ON public.vanna_schema_tables USING btree (id);
CREATE INDEX ix_vanna_schema_tables_datasource_id ON public.vanna_schema_tables USING btree (datasource_id);
CREATE INDEX ix_vanna_schema_tables_schema_name ON public.vanna_schema_tables USING btree (schema_name);
CREATE INDEX ix_vanna_schema_tables_status ON public.vanna_schema_tables USING btree (status);
CREATE INDEX ix_vanna_schema_tables_kb_id ON public.vanna_schema_tables USING btree (kb_id);
CREATE INDEX ix_vanna_schema_tables_system_short ON public.vanna_schema_tables USING btree (system_short);
CREATE INDEX ix_vanna_schema_tables_table_name ON public.vanna_schema_tables USING btree (table_name);
CREATE INDEX ix_vanna_schema_tables_content_hash ON public.vanna_schema_tables USING btree (content_hash);
COMMENT ON TABLE public.vanna_schema_tables IS 'Schema表结构快照表';
COMMENT ON COLUMN public.vanna_schema_tables.id IS '表结构ID';
COMMENT ON COLUMN public.vanna_schema_tables.kb_id IS '知识库ID';
COMMENT ON COLUMN public.vanna_schema_tables.datasource_id IS '数据源ID';
COMMENT ON COLUMN public.vanna_schema_tables.harvest_job_id IS '采集任务ID';
COMMENT ON COLUMN public.vanna_schema_tables.system_short IS '系统简称';
COMMENT ON COLUMN public.vanna_schema_tables.env IS '环境（如prod/dev）';
COMMENT ON COLUMN public.vanna_schema_tables.catalog_name IS '目录名称';
COMMENT ON COLUMN public.vanna_schema_tables.schema_name IS 'Schema名称';
COMMENT ON COLUMN public.vanna_schema_tables.table_name IS '表名称';
COMMENT ON COLUMN public.vanna_schema_tables.table_type IS '表类型（如table/view）';
COMMENT ON COLUMN public.vanna_schema_tables.table_comment IS '表注释';
COMMENT ON COLUMN public.vanna_schema_tables.table_ddl IS '表DDL语句';
COMMENT ON COLUMN public.vanna_schema_tables.primary_key_json IS '主键信息（JSON格式）';
COMMENT ON COLUMN public.vanna_schema_tables.foreign_keys_json IS '外键信息（JSON格式）';
COMMENT ON COLUMN public.vanna_schema_tables.indexes_json IS '索引信息（JSON格式）';
COMMENT ON COLUMN public.vanna_schema_tables.constraints_json IS '约束信息（JSON格式）';
COMMENT ON COLUMN public.vanna_schema_tables.row_count_estimate IS '行数估计';
COMMENT ON COLUMN public.vanna_schema_tables.content_hash IS '内容哈希';
COMMENT ON COLUMN public.vanna_schema_tables.status IS '表状态（active/stale/archived）';
COMMENT ON COLUMN public.vanna_schema_tables.created_at IS '创建时间';
COMMENT ON COLUMN public.vanna_schema_tables.updated_at IS '更新时间';


-- Table: public.vanna_sql_asset_runs
CREATE TABLE public.vanna_sql_asset_runs (
    id integer DEFAULT nextval('vanna_sql_asset_runs_id_seq'::regclass) NOT NULL,
    asset_id integer NOT NULL,
    asset_version_id integer NOT NULL,
    kb_id integer NOT NULL,
    datasource_id integer NOT NULL,
    task_id integer,
    question_text text,
    resolved_by character varying(32) NOT NULL,
    binding_plan_json json,
    bound_params_json json,
    compiled_sql text NOT NULL,
    execution_status character varying(32) NOT NULL,
    execution_result_json json,
    approval_status character varying(32),
    create_user_id integer NOT NULL,
    create_user_name character varying(255),
    created_at timestamp with time zone NOT NULL,
    PRIMARY KEY (id)
);
ALTER TABLE public.vanna_sql_asset_runs ADD CONSTRAINT vanna_sql_asset_runs_asset_id_fkey FOREIGN KEY (asset_id) REFERENCES public.vanna_sql_assets(id);
ALTER TABLE public.vanna_sql_asset_runs ADD CONSTRAINT vanna_sql_asset_runs_asset_version_id_fkey FOREIGN KEY (asset_version_id) REFERENCES public.vanna_sql_asset_versions(id);
ALTER TABLE public.vanna_sql_asset_runs ADD CONSTRAINT vanna_sql_asset_runs_kb_id_fkey FOREIGN KEY (kb_id) REFERENCES public.vanna_knowledge_bases(id);
ALTER TABLE public.vanna_sql_asset_runs ADD CONSTRAINT vanna_sql_asset_runs_datasource_id_fkey FOREIGN KEY (datasource_id) REFERENCES public.text2sql_databases(id);
CREATE INDEX ix_vanna_sql_asset_runs_datasource_id ON public.vanna_sql_asset_runs USING btree (datasource_id);
CREATE INDEX ix_vanna_sql_asset_runs_task_status ON public.vanna_sql_asset_runs USING btree (task_id, execution_status);
CREATE INDEX ix_vanna_sql_asset_runs_create_user_id ON public.vanna_sql_asset_runs USING btree (create_user_id);
CREATE INDEX ix_vanna_sql_asset_runs_execution_status ON public.vanna_sql_asset_runs USING btree (execution_status);
CREATE INDEX ix_vanna_sql_asset_runs_kb_id ON public.vanna_sql_asset_runs USING btree (kb_id);
CREATE INDEX ix_vanna_sql_asset_runs_id ON public.vanna_sql_asset_runs USING btree (id);
CREATE INDEX ix_vanna_sql_asset_runs_task_id ON public.vanna_sql_asset_runs USING btree (task_id);
CREATE INDEX ix_vanna_sql_asset_runs_asset_version_id ON public.vanna_sql_asset_runs USING btree (asset_version_id);
CREATE INDEX ix_vanna_sql_asset_runs_approval_status ON public.vanna_sql_asset_runs USING btree (approval_status);
CREATE INDEX ix_vanna_sql_asset_runs_asset_id ON public.vanna_sql_asset_runs USING btree (asset_id);
CREATE INDEX ix_vanna_sql_asset_runs_asset_created ON public.vanna_sql_asset_runs USING btree (asset_id, created_at);
COMMENT ON TABLE public.vanna_sql_asset_runs IS 'SQL资产运行记录表';
COMMENT ON COLUMN public.vanna_sql_asset_runs.id IS 'SQL资产运行ID';
COMMENT ON COLUMN public.vanna_sql_asset_runs.asset_id IS '资产ID';
COMMENT ON COLUMN public.vanna_sql_asset_runs.asset_version_id IS '资产版本ID';
COMMENT ON COLUMN public.vanna_sql_asset_runs.kb_id IS '知识库ID';
COMMENT ON COLUMN public.vanna_sql_asset_runs.datasource_id IS '数据源ID';
COMMENT ON COLUMN public.vanna_sql_asset_runs.task_id IS '任务ID';
COMMENT ON COLUMN public.vanna_sql_asset_runs.question_text IS '原始问题';
COMMENT ON COLUMN public.vanna_sql_asset_runs.resolved_by IS '命中来源';
COMMENT ON COLUMN public.vanna_sql_asset_runs.binding_plan_json IS '装配计划';
COMMENT ON COLUMN public.vanna_sql_asset_runs.bound_params_json IS '绑定参数';
COMMENT ON COLUMN public.vanna_sql_asset_runs.compiled_sql IS '最终可执行SQL';
COMMENT ON COLUMN public.vanna_sql_asset_runs.execution_status IS '执行状态';
COMMENT ON COLUMN public.vanna_sql_asset_runs.execution_result_json IS '执行结果';
COMMENT ON COLUMN public.vanna_sql_asset_runs.approval_status IS '审批状态';
COMMENT ON COLUMN public.vanna_sql_asset_runs.create_user_id IS '创建用户ID';
COMMENT ON COLUMN public.vanna_sql_asset_runs.create_user_name IS '创建用户名';
COMMENT ON COLUMN public.vanna_sql_asset_runs.created_at IS '创建时间';


-- Table: public.vanna_sql_asset_versions
CREATE TABLE public.vanna_sql_asset_versions (
    id integer DEFAULT nextval('vanna_sql_asset_versions_id_seq'::regclass) NOT NULL,
    asset_id integer NOT NULL,
    version_no integer NOT NULL,
    version_label character varying(64),
    template_sql text NOT NULL,
    parameter_schema_json json NOT NULL,
    render_config_json json,
    statement_kind character varying(32) NOT NULL,
    tables_read_json json,
    columns_read_json json,
    output_fields_json json,
    verification_result_json json,
    quality_status character varying(32) NOT NULL,
    is_published boolean NOT NULL,
    published_at timestamp with time zone,
    created_by character varying(255),
    created_at timestamp with time zone NOT NULL,
    PRIMARY KEY (id)
);
ALTER TABLE public.vanna_sql_asset_versions ADD CONSTRAINT vanna_sql_asset_versions_asset_id_fkey FOREIGN KEY (asset_id) REFERENCES public.vanna_sql_assets(id);
CREATE INDEX ix_vanna_sql_asset_versions_asset_published ON public.vanna_sql_asset_versions USING btree (asset_id, is_published);
CREATE INDEX ix_vanna_sql_asset_versions_quality_status ON public.vanna_sql_asset_versions USING btree (quality_status);
CREATE INDEX ix_vanna_sql_asset_versions_asset_id ON public.vanna_sql_asset_versions USING btree (asset_id);
CREATE INDEX ix_vanna_sql_asset_versions_id ON public.vanna_sql_asset_versions USING btree (id);
COMMENT ON TABLE public.vanna_sql_asset_versions IS 'SQL资产版本表';
COMMENT ON COLUMN public.vanna_sql_asset_versions.id IS 'SQL资产版本ID';
COMMENT ON COLUMN public.vanna_sql_asset_versions.asset_id IS '资产ID';
COMMENT ON COLUMN public.vanna_sql_asset_versions.version_no IS '版本号';
COMMENT ON COLUMN public.vanna_sql_asset_versions.version_label IS '版本标签';
COMMENT ON COLUMN public.vanna_sql_asset_versions.template_sql IS 'SQL模板';
COMMENT ON COLUMN public.vanna_sql_asset_versions.parameter_schema_json IS '参数契约';
COMMENT ON COLUMN public.vanna_sql_asset_versions.render_config_json IS '渲染配置';
COMMENT ON COLUMN public.vanna_sql_asset_versions.statement_kind IS '语句类型';
COMMENT ON COLUMN public.vanna_sql_asset_versions.tables_read_json IS '读取表集合';
COMMENT ON COLUMN public.vanna_sql_asset_versions.columns_read_json IS '读取列集合';
COMMENT ON COLUMN public.vanna_sql_asset_versions.output_fields_json IS '输出字段集合';
COMMENT ON COLUMN public.vanna_sql_asset_versions.verification_result_json IS '验证结果';
COMMENT ON COLUMN public.vanna_sql_asset_versions.quality_status IS '质量状态';
COMMENT ON COLUMN public.vanna_sql_asset_versions.is_published IS '是否已发布';
COMMENT ON COLUMN public.vanna_sql_asset_versions.published_at IS '发布时间';
COMMENT ON COLUMN public.vanna_sql_asset_versions.created_by IS '创建人';
COMMENT ON COLUMN public.vanna_sql_asset_versions.created_at IS '创建时间';


-- Table: public.vanna_sql_assets
CREATE TABLE public.vanna_sql_assets (
    id integer DEFAULT nextval('vanna_sql_assets_id_seq'::regclass) NOT NULL,
    kb_id integer NOT NULL,
    datasource_id integer NOT NULL,
    asset_code character varying(255) NOT NULL,
    name character varying(255) NOT NULL,
    description text,
    intent_summary text,
    asset_kind character varying(32) NOT NULL,
    status character varying(32) NOT NULL,
    system_short character varying(64) NOT NULL,
    database_name character varying(255),
    env character varying(32) NOT NULL,
    match_keywords_json json,
    match_examples_json json,
    owner_user_id integer NOT NULL,
    owner_user_name character varying(255),
    current_version_id integer,
    origin_ask_run_id integer,
    origin_training_entry_id integer,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    PRIMARY KEY (id)
);
ALTER TABLE public.vanna_sql_assets ADD CONSTRAINT vanna_sql_assets_kb_id_fkey FOREIGN KEY (kb_id) REFERENCES public.vanna_knowledge_bases(id);
ALTER TABLE public.vanna_sql_assets ADD CONSTRAINT vanna_sql_assets_datasource_id_fkey FOREIGN KEY (datasource_id) REFERENCES public.text2sql_databases(id);
ALTER TABLE public.vanna_sql_assets ADD CONSTRAINT vanna_sql_assets_origin_ask_run_id_fkey FOREIGN KEY (origin_ask_run_id) REFERENCES public.vanna_ask_runs(id);
ALTER TABLE public.vanna_sql_assets ADD CONSTRAINT vanna_sql_assets_origin_training_entry_id_fkey FOREIGN KEY (origin_training_entry_id) REFERENCES public.vanna_training_entries(id);
CREATE INDEX ix_vanna_sql_assets_database_name ON public.vanna_sql_assets USING btree (database_name);
CREATE INDEX ix_vanna_sql_assets_datasource_id ON public.vanna_sql_assets USING btree (datasource_id);
CREATE INDEX ix_vanna_sql_assets_id ON public.vanna_sql_assets USING btree (id);
CREATE INDEX ix_vanna_sql_assets_system_env_status ON public.vanna_sql_assets USING btree (system_short, env, status);
CREATE INDEX ix_vanna_sql_assets_kb_id ON public.vanna_sql_assets USING btree (kb_id);
CREATE INDEX ix_vanna_sql_assets_current_version_id ON public.vanna_sql_assets USING btree (current_version_id);
CREATE INDEX ix_vanna_sql_assets_status ON public.vanna_sql_assets USING btree (status);
CREATE INDEX ix_vanna_sql_assets_env ON public.vanna_sql_assets USING btree (env);
CREATE INDEX ix_vanna_sql_assets_origin_ask_run_id ON public.vanna_sql_assets USING btree (origin_ask_run_id);
CREATE INDEX ix_vanna_sql_assets_origin_training_entry_id ON public.vanna_sql_assets USING btree (origin_training_entry_id);
CREATE INDEX ix_vanna_sql_assets_system_short ON public.vanna_sql_assets USING btree (system_short);
CREATE INDEX ix_vanna_sql_assets_datasource_status ON public.vanna_sql_assets USING btree (datasource_id, status);
CREATE UNIQUE INDEX ix_vanna_sql_assets_asset_code ON public.vanna_sql_assets USING btree (asset_code);
CREATE INDEX ix_vanna_sql_assets_owner_user_id ON public.vanna_sql_assets USING btree (owner_user_id);
CREATE INDEX ix_vanna_sql_assets_kb_status ON public.vanna_sql_assets USING btree (kb_id, status);
COMMENT ON TABLE public.vanna_sql_assets IS 'SQL资产表';
COMMENT ON COLUMN public.vanna_sql_assets.id IS 'SQL资产ID';
COMMENT ON COLUMN public.vanna_sql_assets.kb_id IS '知识库ID';
COMMENT ON COLUMN public.vanna_sql_assets.datasource_id IS '数据源ID';
COMMENT ON COLUMN public.vanna_sql_assets.asset_code IS '资产唯一编码';
COMMENT ON COLUMN public.vanna_sql_assets.name IS '资产名称';
COMMENT ON COLUMN public.vanna_sql_assets.description IS '资产描述';
COMMENT ON COLUMN public.vanna_sql_assets.intent_summary IS '用途摘要';
COMMENT ON COLUMN public.vanna_sql_assets.asset_kind IS '资产类型';
COMMENT ON COLUMN public.vanna_sql_assets.status IS '资产状态';
COMMENT ON COLUMN public.vanna_sql_assets.system_short IS '系统简称';
COMMENT ON COLUMN public.vanna_sql_assets.database_name IS '逻辑数据库名称';
COMMENT ON COLUMN public.vanna_sql_assets.env IS '环境';
COMMENT ON COLUMN public.vanna_sql_assets.match_keywords_json IS '检索关键词';
COMMENT ON COLUMN public.vanna_sql_assets.match_examples_json IS '检索示例';
COMMENT ON COLUMN public.vanna_sql_assets.owner_user_id IS '所有者用户ID';
COMMENT ON COLUMN public.vanna_sql_assets.owner_user_name IS '所有者用户名';
COMMENT ON COLUMN public.vanna_sql_assets.current_version_id IS '当前发布版本ID';
COMMENT ON COLUMN public.vanna_sql_assets.origin_ask_run_id IS '来源Ask运行ID';
COMMENT ON COLUMN public.vanna_sql_assets.origin_training_entry_id IS '来源训练条目ID';
COMMENT ON COLUMN public.vanna_sql_assets.created_at IS '创建时间';
COMMENT ON COLUMN public.vanna_sql_assets.updated_at IS '更新时间';


-- Table: public.vanna_training_entries
CREATE TABLE public.vanna_training_entries (
    id integer DEFAULT nextval('vanna_training_entries_id_seq'::regclass) NOT NULL,
    kb_id integer NOT NULL,
    datasource_id integer NOT NULL,
    system_short character varying(64) NOT NULL,
    env character varying(32) NOT NULL,
    entry_code character varying(255) NOT NULL,
    entry_type character varying(32) NOT NULL,
    source_kind character varying(32),
    source_ref character varying(255),
    lifecycle_status character varying(32) NOT NULL,
    quality_status character varying(32) NOT NULL,
    title character varying(255),
    question_text text,
    sql_text text,
    sql_explanation text,
    doc_text text,
    schema_name character varying(255),
    table_name character varying(255),
    business_domain character varying(128),
    system_name character varying(128),
    subject_area character varying(128),
    statement_kind character varying(32),
    tables_read_json json,
    columns_read_json json,
    output_fields_json json,
    variables_json json,
    tags_json json,
    verification_result_json json,
    quality_score double precision,
    content_hash character varying(64),
    create_user_id integer NOT NULL,
    create_user_name character varying(255),
    verified_by character varying(255),
    verified_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    PRIMARY KEY (id)
);
ALTER TABLE public.vanna_training_entries ADD CONSTRAINT vanna_training_entries_kb_id_fkey FOREIGN KEY (kb_id) REFERENCES public.vanna_knowledge_bases(id);
ALTER TABLE public.vanna_training_entries ADD CONSTRAINT vanna_training_entries_datasource_id_fkey FOREIGN KEY (datasource_id) REFERENCES public.text2sql_databases(id);
CREATE UNIQUE INDEX ix_vanna_training_entries_entry_code ON public.vanna_training_entries USING btree (entry_code);
CREATE INDEX ix_vanna_training_entries_kb_id ON public.vanna_training_entries USING btree (kb_id);
CREATE INDEX ix_vanna_training_entries_subject_area ON public.vanna_training_entries USING btree (subject_area);
CREATE INDEX ix_vanna_training_entries_create_user_id ON public.vanna_training_entries USING btree (create_user_id);
CREATE INDEX ix_vanna_training_entries_business_domain ON public.vanna_training_entries USING btree (business_domain);
CREATE INDEX ix_vanna_training_entries_lifecycle_status ON public.vanna_training_entries USING btree (lifecycle_status);
CREATE INDEX ix_vanna_training_entries_statement_kind ON public.vanna_training_entries USING btree (statement_kind);
CREATE INDEX ix_vanna_training_entries_system_short ON public.vanna_training_entries USING btree (system_short);
CREATE INDEX ix_vanna_training_entries_entry_type ON public.vanna_training_entries USING btree (entry_type);
CREATE INDEX ix_vanna_training_entries_content_hash ON public.vanna_training_entries USING btree (content_hash);
CREATE INDEX ix_vanna_training_entries_id ON public.vanna_training_entries USING btree (id);
CREATE INDEX ix_vanna_training_entries_schema_name ON public.vanna_training_entries USING btree (schema_name);
CREATE INDEX ix_vanna_training_entries_system_name ON public.vanna_training_entries USING btree (system_name);
CREATE INDEX ix_vanna_training_entries_quality_status ON public.vanna_training_entries USING btree (quality_status);
CREATE INDEX ix_vanna_training_entries_datasource_id ON public.vanna_training_entries USING btree (datasource_id);
CREATE INDEX ix_vanna_training_entries_env ON public.vanna_training_entries USING btree (env);
CREATE INDEX ix_vanna_training_entries_source_kind ON public.vanna_training_entries USING btree (source_kind);
CREATE INDEX ix_vanna_training_entries_table_name ON public.vanna_training_entries USING btree (table_name);
COMMENT ON TABLE public.vanna_training_entries IS '训练条目表';
COMMENT ON COLUMN public.vanna_training_entries.id IS '训练条目ID';
COMMENT ON COLUMN public.vanna_training_entries.kb_id IS '知识库ID';
COMMENT ON COLUMN public.vanna_training_entries.datasource_id IS '数据源ID';
COMMENT ON COLUMN public.vanna_training_entries.system_short IS '系统简称';
COMMENT ON COLUMN public.vanna_training_entries.env IS '环境（如prod/dev）';
COMMENT ON COLUMN public.vanna_training_entries.entry_code IS '训练条目唯一编码';
COMMENT ON COLUMN public.vanna_training_entries.entry_type IS '条目类型（question_sql/schema_summary/documentation）';
COMMENT ON COLUMN public.vanna_training_entries.source_kind IS '来源类型（manual/auto_import/harvest）';
COMMENT ON COLUMN public.vanna_training_entries.source_ref IS '来源引用';
COMMENT ON COLUMN public.vanna_training_entries.lifecycle_status IS '生命周期状态（candidate/published/archived）';
COMMENT ON COLUMN public.vanna_training_entries.quality_status IS '质量状态（unverified/verified/rejected）';
COMMENT ON COLUMN public.vanna_training_entries.title IS '标题';
COMMENT ON COLUMN public.vanna_training_entries.question_text IS '问题文本';
COMMENT ON COLUMN public.vanna_training_entries.sql_text IS 'SQL语句';
COMMENT ON COLUMN public.vanna_training_entries.sql_explanation IS 'SQL解释';
COMMENT ON COLUMN public.vanna_training_entries.doc_text IS '文档文本';
COMMENT ON COLUMN public.vanna_training_entries.schema_name IS 'Schema名称';
COMMENT ON COLUMN public.vanna_training_entries.table_name IS '表名称';
COMMENT ON COLUMN public.vanna_training_entries.business_domain IS '业务域';
COMMENT ON COLUMN public.vanna_training_entries.system_name IS '系统名称';
COMMENT ON COLUMN public.vanna_training_entries.subject_area IS '主题域';
COMMENT ON COLUMN public.vanna_training_entries.statement_kind IS '语句类型（SELECT/INSERT/UPDATE/DELETE）';
COMMENT ON COLUMN public.vanna_training_entries.tables_read_json IS '读取的表列表（JSON格式）';
COMMENT ON COLUMN public.vanna_training_entries.columns_read_json IS '读取的字段列表（JSON格式）';
COMMENT ON COLUMN public.vanna_training_entries.output_fields_json IS '输出字段列表（JSON格式）';
COMMENT ON COLUMN public.vanna_training_entries.variables_json IS '变量列表（JSON格式）';
COMMENT ON COLUMN public.vanna_training_entries.tags_json IS '标签列表（JSON格式）';
COMMENT ON COLUMN public.vanna_training_entries.verification_result_json IS '验证结果（JSON格式）';
COMMENT ON COLUMN public.vanna_training_entries.quality_score IS '质量分数';
COMMENT ON COLUMN public.vanna_training_entries.content_hash IS '内容哈希';
COMMENT ON COLUMN public.vanna_training_entries.create_user_id IS '创建用户ID';
COMMENT ON COLUMN public.vanna_training_entries.create_user_name IS '创建用户名';
COMMENT ON COLUMN public.vanna_training_entries.verified_by IS '验证人';
COMMENT ON COLUMN public.vanna_training_entries.verified_at IS '验证时间';
COMMENT ON COLUMN public.vanna_training_entries.created_at IS '创建时间';
COMMENT ON COLUMN public.vanna_training_entries.updated_at IS '更新时间';


-- ============================================
-- Schema: xagent_vector
-- ============================================
CREATE SCHEMA IF NOT EXISTS xagent_vector;

-- Table: xagent_vector._table_metadata
CREATE TABLE xagent_vector._table_metadata (
    table_name text NOT NULL,
    schema_json jsonb NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    PRIMARY KEY (table_name)
);
COMMENT ON TABLE xagent_vector._table_metadata IS '表元数据管理表';
COMMENT ON COLUMN xagent_vector._table_metadata.table_name IS '表名';
COMMENT ON COLUMN xagent_vector._table_metadata.schema_json IS '表结构Schema(JSON)';
COMMENT ON COLUMN xagent_vector._table_metadata.updated_at IS '更新时间';


-- Table: xagent_vector.chunks
CREATE TABLE xagent_vector.chunks (
    collection text,
    doc_id text,
    parse_hash text,
    chunk_id text,
    index integer,
    text text,
    page_number integer,
    section text,
    anchor text,
    json_path text,
    chunk_hash text,
    config_hash text,
    created_at timestamp with time zone,
    metadata text,
    user_id bigint
);
COMMENT ON TABLE xagent_vector.chunks IS '文档分块表';
COMMENT ON COLUMN xagent_vector.chunks.collection IS '集合名称';
COMMENT ON COLUMN xagent_vector.chunks.doc_id IS '文档ID';
COMMENT ON COLUMN xagent_vector.chunks.parse_hash IS '解析哈希';
COMMENT ON COLUMN xagent_vector.chunks.chunk_id IS '分块ID';
COMMENT ON COLUMN xagent_vector.chunks.index IS '分块序号';
COMMENT ON COLUMN xagent_vector.chunks.text IS '分块文本内容';
COMMENT ON COLUMN xagent_vector.chunks.page_number IS '页码';
COMMENT ON COLUMN xagent_vector.chunks.section IS '章节';
COMMENT ON COLUMN xagent_vector.chunks.anchor IS '锚点';
COMMENT ON COLUMN xagent_vector.chunks.json_path IS 'JSON路径';
COMMENT ON COLUMN xagent_vector.chunks.chunk_hash IS '分块内容哈希';
COMMENT ON COLUMN xagent_vector.chunks.config_hash IS '配置哈希';
COMMENT ON COLUMN xagent_vector.chunks.created_at IS '创建时间';
COMMENT ON COLUMN xagent_vector.chunks.metadata IS '元数据';
COMMENT ON COLUMN xagent_vector.chunks.user_id IS '用户ID';


-- Table: xagent_vector.collection_config
CREATE TABLE xagent_vector.collection_config (
    collection text,
    config_json text,
    updated_at timestamp with time zone,
    user_id bigint
);
COMMENT ON TABLE xagent_vector.collection_config IS '集合配置表';
COMMENT ON COLUMN xagent_vector.collection_config.collection IS '集合名称';
COMMENT ON COLUMN xagent_vector.collection_config.config_json IS '配置JSON';
COMMENT ON COLUMN xagent_vector.collection_config.updated_at IS '更新时间';
COMMENT ON COLUMN xagent_vector.collection_config.user_id IS '用户ID';


-- Table: xagent_vector.documents
CREATE TABLE xagent_vector.documents (
    collection text,
    doc_id text,
    file_id text,
    source_path text,
    file_type text,
    content_hash text,
    uploaded_at timestamp with time zone,
    title text,
    language text,
    user_id bigint
);
COMMENT ON TABLE xagent_vector.documents IS '文档存储表';
COMMENT ON COLUMN xagent_vector.documents.collection IS '集合名称';
COMMENT ON COLUMN xagent_vector.documents.doc_id IS '文档ID';
COMMENT ON COLUMN xagent_vector.documents.file_id IS '文件ID';
COMMENT ON COLUMN xagent_vector.documents.source_path IS '源文件路径';
COMMENT ON COLUMN xagent_vector.documents.file_type IS '文件类型';
COMMENT ON COLUMN xagent_vector.documents.content_hash IS '内容哈希';
COMMENT ON COLUMN xagent_vector.documents.uploaded_at IS '上传时间';
COMMENT ON COLUMN xagent_vector.documents.title IS '文档标题';
COMMENT ON COLUMN xagent_vector.documents.language IS '语言';
COMMENT ON COLUMN xagent_vector.documents.user_id IS '用户ID';


-- Table: xagent_vector.memories
CREATE TABLE xagent_vector.memories (
    id text,
    text text,
    metadata text,
    vector USER-DEFINED
);
COMMENT ON TABLE xagent_vector.memories IS '记忆向量表';
COMMENT ON COLUMN xagent_vector.memories.id IS '记忆ID';
COMMENT ON COLUMN xagent_vector.memories.text IS '记忆文本';
COMMENT ON COLUMN xagent_vector.memories.metadata IS '元数据';
COMMENT ON COLUMN xagent_vector.memories.vector IS '向量数据';


-- Table: xagent_vector.parses
CREATE TABLE xagent_vector.parses (
    collection text,
    doc_id text,
    parse_hash text,
    parser text,
    created_at timestamp with time zone,
    params_json text,
    parsed_content text,
    user_id bigint
);
COMMENT ON TABLE xagent_vector.parses IS '文档解析记录表';
COMMENT ON COLUMN xagent_vector.parses.collection IS '集合名称';
COMMENT ON COLUMN xagent_vector.parses.doc_id IS '文档ID';
COMMENT ON COLUMN xagent_vector.parses.parse_hash IS '解析哈希';
COMMENT ON COLUMN xagent_vector.parses.parser IS '解析器类型';
COMMENT ON COLUMN xagent_vector.parses.created_at IS '创建时间';
COMMENT ON COLUMN xagent_vector.parses.params_json IS '解析参数(JSON)';
COMMENT ON COLUMN xagent_vector.parses.parsed_content IS '解析后的内容';
COMMENT ON COLUMN xagent_vector.parses.user_id IS '用户ID';


-- Table: xagent_vector.test_fallback
CREATE TABLE xagent_vector.test_fallback (
    id text,
    text text,
    metadata text
);
COMMENT ON TABLE xagent_vector.test_fallback IS '测试回退表';
COMMENT ON COLUMN xagent_vector.test_fallback.id IS '记录ID';
COMMENT ON COLUMN xagent_vector.test_fallback.text IS '文本内容';
COMMENT ON COLUMN xagent_vector.test_fallback.metadata IS '元数据';


-- Table: xagent_vector.test_memories
CREATE TABLE xagent_vector.test_memories (
    id text,
    text text,
    metadata text,
    vector USER-DEFINED
);
COMMENT ON TABLE xagent_vector.test_memories IS '测试记忆向量表';
COMMENT ON COLUMN xagent_vector.test_memories.id IS '记忆ID';
COMMENT ON COLUMN xagent_vector.test_memories.text IS '记忆文本';
COMMENT ON COLUMN xagent_vector.test_memories.metadata IS '元数据';
COMMENT ON COLUMN xagent_vector.test_memories.vector IS '向量数据';

