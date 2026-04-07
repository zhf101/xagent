# Xagent 用户审批管理

## 文档目的

本文档沉淀当前已确认的用户审批管理设计分析，目标是把 Xagent 现有围绕数据源和环境的审批思路，收敛为围绕 `system_short` 的统一权限与审批模型。

本文档当前覆盖：

- 现状分析
- 已确认的业务约束
- 可选方案对比
- 推荐方案与设计原则

后续可在此基础上继续补充：

- 详细表结构
- API 设计
- 迁移方案
- 权限校验流程
- 前后端交互设计

## 一、现状分析

### 1. 资产模型现状

当前系统中，`system_short` 已经进入多个资产模型：

- `Text2SQLDatabase`
- GDP HTTP 资源
- Vanna 相关知识库、训练条目、SQL 资产等

这说明 `system_short` 已经天然承担了一部分“业务归属边界”的职责。

与此同时，`env` 也被广泛存储在资产表中，用于表达资产所属环境，例如 `prod`、`test`、`uat`。

### 2. 审批模型现状

当前审批模型仍然更偏向以下粒度：

- `datasource_id`
- `environment`

也就是说，审批主语更接近“某个数据源在某个环境上的请求”，而不是“某个业务系统下的资产请求”。

这种建模与后续诉求存在偏差，因为后续审批要求明确围绕 `system_short` 组织，而不是围绕单个数据源组织。

### 3. 现有问题

如果继续沿用当前模式，会出现以下问题：

- 审批边界分散：同一业务系统下的数据源、SQL、HTTP 资产无法统一纳入同一套管理员权限
- 权限模型不稳定：审批依赖 `datasource_id`，难以表达“系统管理员”这一稳定角色
- 扩展性差：新增资产类型时，需要重复发明一套与数据源耦合的审批逻辑
- `system_short` 缺乏主数据治理：如果只作为自由输入字符串，后续会出现命名漂移，例如大小写不统一、同义简称并存等

## 二、已确认业务约束

以下约束已经确认：

### 1. `system_short` 是审批的核心边界

审批设计要围绕 `system_short` 展开。

含义是：

- 资产归属可以落到某个 `system_short`
- 审批权限授予给某个 `system_short` 下的管理员
- 审批判断以 `system_short` 为核心条件，而不是以单个数据源为核心条件

### 2. 用户与系统是多对多关系

需要支持：

- 一个用户可以对应多个 `system_short`
- 一个 `system_short` 可以对应多个用户

### 3. 管理员按系统维度授予

只要某个用户属于某个 `system_short` 的管理员，就可以审批属于该 `system_short` 的资产，例如：

- 数据源
- SQL 资产
- HTTP 接口资产

### 4. `env` 不参与审批授权边界

`env` 已确认只作为资产属性存在，不作为审批权限判断条件。

也就是说：

- `CRM/prod` 和 `CRM/test` 在审批授权上都归属于 `CRM`
- 审批权限只看 `system_short`
- `env` 仅用于展示、筛选、审计上下文和资产属性表达

### 5. 角色划分

已确认采用系统内维护关系的方式，支持以下角色：

- `admin`
- `system_admin`
- `member`

权限边界确认如下：

- `admin` 是全局管理员，平台级角色
- `system_admin` 是指定 `system_short` 的管理员
- `member` 不具备审批权
- 普通用户和 `member` 都可以发起资产新增、修改、删除申请
- 任何资产变更都不能直接生效，必须由该 `system_short` 的 `system_admin` 或全局 `admin` 审批

## 三、方案对比

### 方案 A：最小改造

做法：

- 新增用户与 `system_short` 的角色映射表
- 资产继续只存字符串 `system_short`
- 审批时根据资产上的 `system_short` 判断当前用户是否为该系统管理员

优点：

- 改动最小
- 落地快

缺点：

- 没有系统主数据表
- `system_short` 规范化问题无法彻底解决
- 后续容易出现脏数据，例如大小写不一致、别名并存

### 方案 B：推荐方案

做法：

- 引入系统主数据表 `system_registry`
- 引入用户系统角色表 `user_system_roles`
- 所有资产仍保留 `system_short` 字段作为快照和查询键
- 但创建和更新时必须通过 `system_registry` 做校验和标准化
- 审批请求和审批账本逐步切换为以 `system_short` 为中心

优点：

- 满足多对多关系建模
- 解决 `system_short` 规范化问题
- 审批主语稳定清晰
- 对现有资产表改动可控
- 便于后续纳管更多资产类型

缺点：

- 需要补充系统主数据与角色管理接口
- 迁移量中等

### 方案 C：强规范化重构

做法：

- 所有资产不再直接依赖 `system_short` 字符串
- 引入额外内部主键做关联
- 读取时再关联出 `system_short`

优点：

- 数据一致性最强
- 长期结构最标准

缺点：

- 迁移范围最大
- 需要改动大量模型、接口、查询和前端类型
- 当前阶段性价比不高

## 四、推荐方案

推荐采用方案 B：`system_registry + user_system_roles + 资产保留 system_short 快照`

这是当前最平衡的方案，原因如下：

- 能把 `system_short` 提升为正式的领域对象，避免脏数据扩散
- 能满足“一个用户多个系统、一个系统多个用户”的关系要求
- 能让审批能力从单个数据源抽离，提升为系统级能力
- 不需要一次性把所有资产彻底重构成 `system_id` 外键模式
- 能兼顾当前代码现状与后续演进空间

## 五、推荐领域模型

### 1. `SystemRegistry`

职责：

- 承载系统主数据
- 统一管理规范化后的 `system_short`
- 为资产归属和审批边界提供唯一来源

建议字段：

- `system_short`
- `display_name`
- `status`
- `description`
- `created_by`
- `created_at`
- `updated_at`

约束建议：

- `system_short` 全局唯一
- `system_short` 需要统一规范化规则，例如统一大写或统一 slug
- `system_short` 采用自然主键，不引入 `system_id`

### 2. `UserSystemRole`

职责：

- 表达用户在某个系统下的角色

建议字段：

- `id`
- `user_id`
- `system_short`
- `role`，取值至少包含 `member`、`system_admin`
- `granted_by`
- `created_at`

约束建议：

- `(user_id, system_short)` 唯一

### 3. 资产模型

所有可审批资产都必须带有规范化后的 `system_short`。

建议：

- 现阶段继续保留资产表内的 `system_short`
- 该字段作为业务快照、检索键、筛选键
- 但写入时必须校验该值是否存在于 `system_registry` 中
- 资产侧不得再接受未注册的自由输入系统简称

### 4. `env`

`env` 的定位明确为资产属性，不属于审批授权模型的一部分。

它可以继续用于：

- 页面展示
- 资产筛选
- 风险提示
- 审计日志
- 数据隔离描述

但不用于：

- 审批权限判断
- 系统管理员关系判断
- 审批路由分派

## 六、审批设计原则

围绕 `system_short` 设计审批时，建议遵循以下原则：

### 1. 审批权属于系统管理员，不属于数据源管理员

审批主体必须从“数据源”提升到“系统”。

只要当前用户是该 `system_short` 的 `system_admin`，就可以审批该系统下的资产请求；全局 `admin` 具备兜底审批能力。

### 2. 资产类型共享同一套审批边界

以下资产应共享同一套 `system_short` 授权逻辑：

- 数据源
- SQL 资产
- HTTP 资产
- 后续新增的系统级资产

### 3. 创建与审批分离

普通用户和 `member` 都可以提交资产变更，但是否生效由 `system_admin` 或全局 `admin` 决定。

这样可以实现：

- 协作者可录入和维护资产
- 审批权保持集中
- 权限边界清晰

### 4. 审批逻辑必须可复用

不同资产类型不应各自维护一套系统管理员判断逻辑。

应抽出统一的系统级授权判断能力，例如：

- 判断某用户是否属于某系统
- 判断某用户是否为某系统管理员
- 根据资产反查归属系统

## 七、当前结论

当前已经确认的结论如下：

1. `system_short` 是 Xagent 后续审批管理的一级边界
2. `system_short` 采用自然主键，不引入 `system_id`
3. `env` 仅是资产属性，不参与审批授权
4. 用户与系统是多对多关系
5. 全局 `admin` 是平台管理员，`system_admin` 是指定 `system_short` 的管理员
6. 只有全局 `admin` 可以创建 `system_short` 和分配系统角色
7. 普通用户可以查看和使用所有系统资产
8. 普通用户对任何资产的新增、修改、删除都需要审批后生效
9. 推荐引入 `system_registry` 和 `user_system_roles` 两张核心表
10. 推荐保留资产表中的 `system_short` 作为快照字段，但必须通过系统主数据做校验和规范化

## 八、下一步建议

后续详细设计建议继续沿以下方向展开：

1. 定义 `system_registry` 与 `user_system_roles` 表结构和迁移方案
2. 重新定义审批请求与审批账本的系统级归属字段
3. 梳理数据源、SQL 资产、HTTP 资产的统一归属校验流程
4. 设计系统管理员维护接口与页面
5. 设计资产提交、待审批、审批通过、审批拒绝的统一状态流转

## 九、详细设计

### 1. 权限与审批模型

- `admin` 是全局管理员，平台级角色
- `system_admin` 是某个指定 `system_short` 的管理员
- `system_short` 自身是唯一标识，所有后续关联均直接使用 `system_short`
- 只有全局 `admin` 可以创建 `system_short`
- 只有全局 `admin` 可以给用户分配某个 `system_short` 下的 `member` / `system_admin`
- 普通用户可以查看和使用所有系统资产
- 普通用户对任何系统资产的 `create / update / delete` 都需要审批
- `system_admin` 负责审批自己所管理 `system_short` 下的资产变更
- 全局 `admin` 具备审批兜底能力，可以审批任何 `system_short` 下的请求

审批判断规则：

- 当前用户是全局 `admin`，允许审批任意请求
- 当前用户是该 `system_short` 的 `system_admin`，允许审批该系统请求
- 其他用户只能发起申请，不能审批

### 2. 资产状态机与审批流

建议所有可审批资产共享同一套业务状态：

- `draft`
- `pending_approval`
- `approved`
- `rejected`
- `archived`

建议采用“正式资产 + 变更申请”双层模型：

- 正式资产表承载当前生效版本
- 任何新增、修改、删除都先生成审批申请
- 审批通过后，再把申请内容投影到正式资产

动作语义统一为：

- `create`
- `update`
- `delete`

删除建议采用逻辑删除，即审批通过后将正式资产置为 `archived`，不做物理删除。

### 3. 核心表结构

#### 3.1 `system_registry`

用途：注册所有合法的 `system_short`

建议字段：

- `system_short`：主键，唯一，自然主键
- `display_name`
- `description`
- `status`：`active` / `disabled`
- `created_by`
- `created_at`
- `updated_at`

#### 3.2 `user_system_roles`

用途：定义用户在某个 `system_short` 下的角色

建议字段：

- `id`
- `user_id`
- `system_short`
- `role`：`member` / `system_admin`
- `granted_by`
- `created_at`

约束：

- `(user_id, system_short)` 唯一
- `system_short` 必须存在于 `system_registry`

#### 3.3 正式资产层

现有正式资产表可以继续保留，例如：

- `text2sql_databases`
- `gdp_http_resources`
- `vanna_sql_assets`

统一要求：

- 每张表必须有 `system_short`
- `env` 继续保留为资产属性
- 只有审批通过后的版本才能进入正式表
- 正式表建议加上审批元数据：
`created_by`、`updated_by`、`approved_by`、`approved_at`、`approval_request_id`、`status`

#### 3.4 `asset_change_requests`

用途：统一承载资产新增、修改、删除申请

建议字段：

- `id`
- `request_type`：`create` / `update` / `delete`
- `asset_type`：`datasource` / `sql_asset` / `http_resource`
- `asset_id`
- `system_short`
- `env`
- `status`：`draft` / `pending_approval` / `approved` / `rejected` / `cancelled` / `superseded`
- `requested_by`
- `requested_at`
- `submitted_at`
- `approved_by`
- `approved_at`
- `rejected_by`
- `rejected_at`
- `reject_reason`
- `change_summary`
- `payload_snapshot`
- `current_snapshot`
- `approval_comment`

说明：

- `payload_snapshot` 保存拟生效内容
- `current_snapshot` 保存提交时的正式资产内容
- `system_short` 为审批路由核心字段，必须冗余保存

#### 3.5 `asset_change_request_logs`

用途：记录审批申请的完整操作轨迹

建议字段：

- `id`
- `request_id`
- `action`：`draft_saved` / `submitted` / `approved` / `rejected` / `cancelled`
- `operator_user_id`
- `operator_role`
- `comment`
- `created_at`
- `snapshot`

### 4. 关键流程

#### 4.1 新增资产

- 用户填写新增表单
- 系统校验 `system_short` 必须存在于 `system_registry`
- 不直接写正式资产表
- 先创建 `asset_change_requests`
- `request_type = create`
- `status = pending_approval`
- 审批通过后，系统把 `payload_snapshot` 投影到正式资产表

#### 4.2 修改资产

- 用户编辑已存在资产
- 系统读取正式资产当前版本
- 创建 `asset_change_requests`
- `request_type = update`
- `asset_id` 指向正式资产
- `current_snapshot` 保存旧版本
- `payload_snapshot` 保存新版本
- 审批通过后，再把 `payload_snapshot` 覆盖到正式资产

#### 4.3 删除资产

- 用户发起删除
- 创建 `asset_change_requests`
- `request_type = delete`
- `current_snapshot` 保存正式资产当前内容
- 审批通过后将正式资产置为 `archived`

#### 4.4 审批通过

- 审批人必须是全局 `admin` 或该 `system_short` 的 `system_admin`
- 将请求状态置为 `approved`
- 写审批日志
- 按 `request_type` 执行正式投影
- 投影成功后更新正式资产上的审批元数据

建议“审批通过”和“正式投影”在事务内处理，避免出现“已批准但未生效”的模糊状态。

#### 4.5 审批拒绝

- 审批人填写拒绝理由
- 请求状态置为 `rejected`
- 写审批日志
- 不修改正式资产

#### 4.6 撤回申请

- 在 `pending_approval` 且尚未处理前，申请人可撤回
- 撤回后状态置为 `cancelled`
- 记录操作日志

#### 4.7 并发控制

建议对修改和删除申请增加版本保护：

- 申请创建时记录正式资产版本号或 `updated_at`
- 审批通过前再次比对正式资产是否已变化
- 若正式资产已被其他已批准请求更新，则当前请求置为 `superseded`

### 5. 权限判定与接口边界

#### 5.1 角色语义

全局角色：

- `admin`

系统角色：

- `member`
- `system_admin`

读取权限原则：

- 普通用户可以读取所有系统资产
- 权限控制重点放在“资产变更是否生效”和“谁可以审批”

#### 5.2 建议抽取统一权限函数

- `is_global_admin(user_id) -> bool`
- `has_system_role(user_id, system_short, role) -> bool`
- `can_approve_system_request(user_id, system_short) -> bool`
- `can_manage_system_asset(user_id, system_short) -> bool`
- `can_submit_asset_request(user_id, system_short) -> bool`

#### 5.3 接口边界

建议按四组接口拆分：

1. 系统主数据接口
2. 系统成员角色接口
3. 资产申请接口
4. 审批接口

系统主数据和系统成员角色接口只允许全局 `admin` 调用。

审批接口规则：

- 全局 `admin` 可查看和审批全部请求
- `system_admin` 只能查看和审批自己负责的 `system_short`

资产读取接口原则上不按 `system_short` 做权限隔离。

### 6. 迁移策略与落地顺序

建议采用分阶段迁移，避免一次性重构所有资产和审批逻辑。

#### 阶段 1：建立系统主数据与角色关系

- 新增 `system_registry`
- 新增 `user_system_roles`
- 为现有资产表的 `system_short` 做规范化清洗
- 补充系统主数据管理与角色分配接口

目标：

- 先让 `system_short` 成为受控主数据
- 先建立全局 `admin`、`system_admin`、`member` 的授权基础

#### 阶段 2：接入统一资产变更申请模型

- 新增 `asset_change_requests`
- 新增 `asset_change_request_logs`
- 将数据源、HTTP 资产、SQL 资产的新增/修改/删除改为“先申请后审批”

目标：

- 阻断普通用户直接改正式资产
- 建立统一审批入口

#### 阶段 3：将现有审批页面与待办切换到 `system_short` 维度

- 待审批列表按 `system_short` 路由和过滤
- `system_admin` 只看到自己负责系统的待办
- 全局 `admin` 可查看全量待办

目标：

- 从资产类型视角切到系统视角

#### 阶段 4：治理历史审批模型

- 保留现有运行时 SQL 审批模型用于 DAG/执行阻断
- 对资产变更审批使用新模型
- 后续再评估是否抽象统一

目标：

- 避免一次性把运行时 SQL 审批和资产配置审批混在一起
- 先解耦两类语义完全不同的审批场景

#### 阶段 5：补审计、通知和前端统一视图

- 审批时间线
- 审批消息通知
- 按 `system_short` 的统一资产与待办页面

目标：

- 提升可用性和可追踪性

## 十、数据库表设计草案

以下 DDL 为设计草案，字段名和类型可在 Alembic 落地时按当前 ORM 规范微调。

### 1. `system_registry`

建议定义：

```sql
CREATE TABLE system_registry (
    system_short VARCHAR(64) PRIMARY KEY,
    display_name VARCHAR(128) NOT NULL,
    description TEXT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    created_by INTEGER NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX ux_system_registry_system_short
    ON system_registry (system_short);

CREATE INDEX ix_system_registry_status
    ON system_registry (status);
```

设计要求：

- `system_short` 为自然主键
- 写入前必须规范化，例如统一大写、去首尾空格
- `status = disabled` 的系统不允许新提交资产申请

### 2. `user_system_roles`

建议定义：

```sql
CREATE TABLE user_system_roles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    system_short VARCHAR(64) NOT NULL,
    role VARCHAR(32) NOT NULL,
    granted_by INTEGER NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_user_system_roles_role
        CHECK (role IN ('member', 'system_admin')),
    CONSTRAINT fk_user_system_roles_system_short
        FOREIGN KEY (system_short) REFERENCES system_registry(system_short)
);

CREATE UNIQUE INDEX ux_user_system_roles_user_system
    ON user_system_roles (user_id, system_short);

CREATE INDEX ix_user_system_roles_system_role
    ON user_system_roles (system_short, role);

CREATE INDEX ix_user_system_roles_user_id
    ON user_system_roles (user_id);
```

设计要求：

- 同一用户在同一系统下只能有一条角色记录
- 用户升级角色时应更新原记录，不应插入重复行
- 角色分配和撤销都应写审计日志

### 3. `asset_change_requests`

建议定义：

```sql
CREATE TABLE asset_change_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_type VARCHAR(32) NOT NULL,
    asset_type VARCHAR(32) NOT NULL,
    asset_id VARCHAR(128) NULL,
    system_short VARCHAR(64) NOT NULL,
    env VARCHAR(32) NULL,
    status VARCHAR(32) NOT NULL,
    requested_by INTEGER NOT NULL,
    requested_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    submitted_at TIMESTAMP NULL,
    approved_by INTEGER NULL,
    approved_at TIMESTAMP NULL,
    rejected_by INTEGER NULL,
    rejected_at TIMESTAMP NULL,
    reject_reason TEXT NULL,
    change_summary VARCHAR(512) NULL,
    approval_comment TEXT NULL,
    current_version_marker VARCHAR(128) NULL,
    current_snapshot JSON NOT NULL,
    payload_snapshot JSON NOT NULL,
    CONSTRAINT ck_asset_change_requests_request_type
        CHECK (request_type IN ('create', 'update', 'delete')),
    CONSTRAINT ck_asset_change_requests_asset_type
        CHECK (asset_type IN ('datasource', 'sql_asset', 'http_resource')),
    CONSTRAINT ck_asset_change_requests_status
        CHECK (
            status IN (
                'draft',
                'pending_approval',
                'approved',
                'rejected',
                'cancelled',
                'superseded'
            )
        ),
    CONSTRAINT fk_asset_change_requests_system_short
        FOREIGN KEY (system_short) REFERENCES system_registry(system_short)
);

CREATE INDEX ix_asset_change_requests_status
    ON asset_change_requests (status);

CREATE INDEX ix_asset_change_requests_system_status
    ON asset_change_requests (system_short, status);

CREATE INDEX ix_asset_change_requests_requester
    ON asset_change_requests (requested_by, status);

CREATE INDEX ix_asset_change_requests_asset_lookup
    ON asset_change_requests (asset_type, asset_id, status);
```

字段说明：

- `asset_id`
  对 `update` / `delete` 必填；对 `create` 可为空
- `current_version_marker`
  用于并发保护，可保存正式资产的 `updated_at`、版本号或哈希
- `current_snapshot`
  提交时正式资产的快照
- `payload_snapshot`
  申请人希望生效的目标内容

### 4. `asset_change_request_logs`

建议定义：

```sql
CREATE TABLE asset_change_request_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id INTEGER NOT NULL,
    action VARCHAR(32) NOT NULL,
    operator_user_id INTEGER NOT NULL,
    operator_role VARCHAR(32) NOT NULL,
    comment TEXT NULL,
    snapshot JSON NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT ck_asset_change_request_logs_action
        CHECK (
            action IN (
                'draft_saved',
                'submitted',
                'approved',
                'rejected',
                'cancelled',
                'superseded'
            )
        ),
    CONSTRAINT fk_asset_change_request_logs_request
        FOREIGN KEY (request_id) REFERENCES asset_change_requests(id)
);

CREATE INDEX ix_asset_change_request_logs_request_id
    ON asset_change_request_logs (request_id, created_at);
```

### 5. 正式资产表补充字段建议

现有正式资产表建议逐步补齐以下字段：

```sql
approved_by INTEGER NULL;
approved_at TIMESTAMP NULL;
approval_request_id INTEGER NULL;
status VARCHAR(32) NOT NULL DEFAULT 'approved';
created_by INTEGER NULL;
updated_by INTEGER NULL;
```

适用对象：

- `text2sql_databases`
- `gdp_http_resources`
- `vanna_sql_assets`

说明：

- 正式资产表继续按资产类型各自承载领域数据
- 审批字段用于回溯“这条正式记录由哪次申请生效”

## 十一、API 设计草案

建议接口统一返回标准信封结构，例如：

```json
{
  "success": true,
  "message": "ok",
  "data": {}
}
```

错误返回建议：

```json
{
  "success": false,
  "message": "permission denied",
  "error_code": "PERMISSION_DENIED"
}
```

### 1. 系统主数据接口

#### 1.1 创建系统

`POST /api/system-registry`

请求：

```json
{
  "system_short": "CRM",
  "display_name": "客户关系管理系统",
  "description": "CRM core system"
}
```

规则：

- 仅全局 `admin`
- `system_short` 写入前统一规范化

响应：

```json
{
  "success": true,
  "data": {
    "system_short": "CRM",
    "display_name": "客户关系管理系统",
    "description": "CRM core system",
    "status": "active"
  }
}
```

#### 1.2 查询系统列表

`GET /api/system-registry`

可选参数：

- `status`
- `keyword`

响应项建议包含：

- `system_short`
- `display_name`
- `status`
- `member_count`
- `system_admin_count`

#### 1.3 更新系统

`PUT /api/system-registry/{system_short}`

说明：

- `system_short` 本身不建议支持随意修改
- 如确需改名，应走专门迁移工具，不应走普通更新接口

建议可更新字段：

- `display_name`
- `description`
- `status`

#### 1.4 删除或停用系统

建议优先提供停用，不建议直接删除：

- `POST /api/system-registry/{system_short}/disable`
- `POST /api/system-registry/{system_short}/enable`

原因：

- 历史资产和审批记录都直接关联 `system_short`
- 物理删除会破坏审计链

### 2. 系统角色接口

#### 2.1 查询系统成员

`GET /api/system-registry/{system_short}/members`

仅全局 `admin`

响应项建议包含：

- `user_id`
- `username`
- `role`
- `granted_by`
- `created_at`

#### 2.2 分配角色

`POST /api/system-registry/{system_short}/members`

请求：

```json
{
  "user_id": 123,
  "role": "system_admin"
}
```

规则：

- 仅全局 `admin`
- `role` 只允许 `member` / `system_admin`

#### 2.3 更新角色

`PUT /api/system-registry/{system_short}/members/{user_id}`

请求：

```json
{
  "role": "member"
}
```

#### 2.4 移除角色

`DELETE /api/system-registry/{system_short}/members/{user_id}`

规则：

- 仅全局 `admin`
- 删除前建议校验该系统是否仍保留至少一名 `system_admin`

### 3. 资产申请接口

#### 3.1 创建草稿申请

`POST /api/asset-change-requests`

请求示例：

```json
{
  "request_type": "create",
  "asset_type": "datasource",
  "system_short": "CRM",
  "env": "prod",
  "change_summary": "新增 CRM 主库数据源",
  "payload_snapshot": {
    "name": "crm_main",
    "type": "mysql",
    "system_short": "CRM",
    "env": "prod",
    "read_only": true
  }
}
```

规则：

- 登录用户可提交
- `system_short` 必须存在且为 `active`
- 不直接改正式资产

#### 3.2 提交审批

`POST /api/asset-change-requests/{id}/submit`

动作：

- 将 `draft` 变为 `pending_approval`
- 记录 `submitted_at`
- 写入日志

#### 3.3 查询我的申请

`GET /api/asset-change-requests/my`

可选参数：

- `status`
- `asset_type`
- `system_short`

#### 3.4 查询申请详情

`GET /api/asset-change-requests/{id}`

返回建议包含：

- 主申请信息
- `current_snapshot`
- `payload_snapshot`
- 审批日志时间线
- 可执行动作集合，例如 `can_submit`、`can_cancel`

#### 3.5 撤回申请

`POST /api/asset-change-requests/{id}/cancel`

规则：

- 仅申请人本人
- 状态必须是 `pending_approval`

### 4. 审批接口

#### 4.1 待审批列表

`GET /api/approval-queue`

可选参数：

- `system_short`
- `asset_type`
- `status=pending_approval`

规则：

- 全局 `admin` 可看全量
- `system_admin` 仅看自己负责的 `system_short`

#### 4.2 审批通过

`POST /api/asset-change-requests/{id}/approve`

请求：

```json
{
  "comment": "字段完整，允许生效"
}
```

动作：

- 校验审批权限
- 校验并发版本
- 写审批日志
- 投影到正式资产
- 更新申请状态为 `approved`

#### 4.3 审批拒绝

`POST /api/asset-change-requests/{id}/reject`

请求：

```json
{
  "reason": "缺少必要字段说明"
}
```

动作：

- 状态置为 `rejected`
- 写审批日志
- 不修改正式资产

### 5. 正式资产接口改造原则

现有正式资产接口建议逐步调整：

- 原 `POST /PUT /DELETE` 不再直接改正式资产
- 改为内部转调 `asset_change_requests`
- `GET` 类查询接口保持读取正式资产，不引入系统级读取拦截

例如：

- `POST /api/text2sql/databases`
  从“直接创建数据源”改为“创建数据源申请”
- `PUT /api/text2sql/databases/{id}`
  从“直接更新数据源”改为“创建更新申请”
- `DELETE /api/text2sql/databases/{id}`
  从“直接删除数据源”改为“创建删除申请”

### 6. 接口响应中的权限提示

为了简化前端判断，建议详情接口返回当前用户的权限投影：

```json
{
  "data": {
    "id": 101,
    "system_short": "CRM",
    "status": "approved"
  },
  "permissions": {
    "can_view": true,
    "can_submit_change": true,
    "can_approve": false,
    "can_manage": false
  }
}
```

这样前端可以直接根据服务端判定来展示按钮，而不需要在页面上重复拼接角色逻辑。
