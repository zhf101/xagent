import { test, expect } from '@playwright/test';

test.describe('GDP HTTP 资产注册自动化测试', () => {
  test.beforeEach(async ({ page }) => {
    // 1. 登录
    await page.goto('http://localhost:3000/login');
    await page.fill('input[placeholder*="用户名"]', 'root');
    await page.fill('input[placeholder*="密码"]', '111111');
    await page.click('button:has-text("登录")');
    
    // 等待进入首页
    await page.waitForURL('**/dashboard');
    
    // 2. 进入 HTTP 资产页面
    await page.goto('http://localhost:3000/datamake/http-assets');
    await page.waitForLoadState('networkidle');
  });

  test('成功注册一个基础的 GET 接口资产', async ({ page }) => {
    // 点击新建接口
    await page.click('button:has-text("新建接口")');
    
    // Step 1: 基础资源
    await page.fill('input[placeholder="crm_user_get"]', 'pw_test_get_asset');
    await page.fill('input[placeholder="CRM"]', 'TEST_SYSTEM');
    await page.fill('textarea[placeholder*="一句话描述"]', '这是一个由 Playwright 自动创建的测试资产');
    await page.click('button:has-text("下一步")');

    // Step 2: 工具定义
    await page.fill('label:has-text("Tool 协议名称") + input', 'get_user_profile');
    await page.fill('textarea[placeholder*="详细描述工具功能"]', '用于查询用户基础资料信息的工具');
    await page.click('button:has-text("下一步")');

    // Step 3: 入参映射 (添加一个简单参数)
    await page.click('button:has-text("添加根节点")');
    await page.fill('input[placeholder="field_key"]', 'user_id');
    await page.fill('input[placeholder="业务描述"]', '用户的唯一 ID');
    // 配置路由
    await page.click('button:has-child(svg.lucide-settings2)'); // 点击设置图标
    await page.selectOption('label:has-text("参数位置") + select', 'query');
    await page.fill('input[placeholder*="默认使用参数名称"]', 'uid');
    await page.keyboard.press('Escape'); // 关闭 Popover
    
    await page.click('button:has-text("下一步")');

    // Step 4: 出参定义 (跳过)
    await page.click('button:has-text("下一步")');

    // Step 5: 执行与响应
    await page.selectOption('label:has-text("方法") + select', 'GET');
    await page.click('button:has-text("物理直连")');
    await page.fill('input[placeholder*="https://api"]', 'https://httpbin.org/get');
    
    // 填写模板
    await page.fill('textarea[placeholder*="例如: 客户 {{ extracted.name }}"]', '查询成功，返回数据：{{ resp_json }}');
    
    // 提交
    await page.click('button:has-text("完成注册")');

    // 验证列表是否存在新资产
    await expect(page.locator('h4:has-text("get_user_profile")')).toBeVisible();
  });

  test('成功注册一个带嵌套参数的 POST 接口资产', async ({ page }) => {
    await page.click('button:has-text("新建接口")');
    
    // Step 1
    await page.fill('input[placeholder="crm_user_get"]', 'pw_test_post_nested');
    await page.fill('input[placeholder="CRM"]', 'TEST_POST');
    await page.click('button:has-text("下一步")');

    // Step 2
    await page.fill('label:has-text("Tool 协议名称") + input', 'create_order_nested');
    await page.fill('textarea[placeholder*="详细描述工具功能"]', '创建复杂嵌套结构的订单');
    await page.click('button:has-text("下一步")');

    // Step 3: 入参映射 (嵌套结构)
    await page.click('button:has-text("添加根节点")');
    await page.fill('input[placeholder="field_key"]', 'order_data');
    await page.selectOption('div.col-span-4 select', 'object'); // 修改为对象类型
    
    // 添加子节点
    await page.click('button:has-text("更多操作")');
    await page.click('button:has-text("添加子节点")');
    await page.fill('input[placeholder="field_key"]:near(:has-text("order_data"))', 'item_id');
    
    await page.click('button:has-text("下一步")');
    await page.click('button:has-text("下一步")');

    // Step 5
    await page.selectOption('label:has-text("方法") + select', 'POST');
    await page.fill('input[placeholder*="https://api"]', 'https://httpbin.org/post');
    await page.click('button:has-text("完成注册")');

    await expect(page.locator('h4:has-text("create_order_nested")')).toBeVisible();
  });
});
