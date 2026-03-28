from __future__ import annotations

from datetime import datetime

import pymysql

MYSQL = dict(host="127.0.0.1", port=3306, user="root", password="root")
MYSQL_DB = "xagent_finance_demo"
SQLITE_URL = r"sqlite:///C:\Users\impor\.xagent\xagent.db"
XAGENT_BASE_URL = "http://127.0.0.1:8000"


DDL = [
    "CREATE TABLE IF NOT EXISTS branches(id INT PRIMARY KEY,code VARCHAR(32) UNIQUE,name VARCHAR(128),city VARCHAR(64),region_name VARCHAR(64),created_at DATETIME) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4",
    "CREATE TABLE IF NOT EXISTS employees(id INT PRIMARY KEY,emp_no VARCHAR(32) UNIQUE,branch_id INT,name VARCHAR(128),title VARCHAR(64),hire_date DATE,FOREIGN KEY(branch_id) REFERENCES branches(id)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4",
    "CREATE TABLE IF NOT EXISTS customers(id INT PRIMARY KEY,customer_no VARCHAR(32) UNIQUE,name VARCHAR(128),customer_type VARCHAR(32),id_no VARCHAR(64),mobile VARCHAR(32),segment VARCHAR(32),branch_id INT,rm_employee_id INT,registered_at DATETIME,FOREIGN KEY(branch_id) REFERENCES branches(id),FOREIGN KEY(rm_employee_id) REFERENCES employees(id)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4",
    "CREATE TABLE IF NOT EXISTS customer_contacts(id INT PRIMARY KEY,customer_id INT,contact_type VARCHAR(32),contact_value VARCHAR(128),is_primary_contact TINYINT(1),FOREIGN KEY(customer_id) REFERENCES customers(id)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4",
    "CREATE TABLE IF NOT EXISTS kyc_profiles(id INT PRIMARY KEY,customer_id INT,kyc_status VARCHAR(32),pep_flag TINYINT(1),income_band VARCHAR(32),updated_at DATETIME,FOREIGN KEY(customer_id) REFERENCES customers(id)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4",
    "CREATE TABLE IF NOT EXISTS risk_profiles(id INT PRIMARY KEY,customer_id INT,risk_score DECIMAL(10,2),risk_level VARCHAR(32),review_cycle_days INT,last_review_at DATETIME,FOREIGN KEY(customer_id) REFERENCES customers(id)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4",
    "CREATE TABLE IF NOT EXISTS credit_scores(id INT PRIMARY KEY,customer_id INT,bureau_name VARCHAR(64),score_date DATE,credit_score INT,score_rating VARCHAR(16),FOREIGN KEY(customer_id) REFERENCES customers(id)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4",
    "CREATE TABLE IF NOT EXISTS deposit_products(id INT PRIMARY KEY,product_code VARCHAR(32) UNIQUE,product_name VARCHAR(128),product_type VARCHAR(32),interest_rate DECIMAL(10,4),currency VARCHAR(16)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4",
    "CREATE TABLE IF NOT EXISTS accounts(id INT PRIMARY KEY,account_no VARCHAR(32) UNIQUE,customer_id INT,branch_id INT,product_id INT,currency VARCHAR(16),account_status VARCHAR(32),opened_at DATETIME,FOREIGN KEY(customer_id) REFERENCES customers(id),FOREIGN KEY(branch_id) REFERENCES branches(id),FOREIGN KEY(product_id) REFERENCES deposit_products(id)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4",
    "CREATE TABLE IF NOT EXISTS account_daily_balances(id INT PRIMARY KEY,account_id INT,balance_date DATE,end_balance DECIMAL(18,2),available_balance DECIMAL(18,2),FOREIGN KEY(account_id) REFERENCES accounts(id)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4",
    "CREATE TABLE IF NOT EXISTS merchants(id INT PRIMARY KEY,merchant_code VARCHAR(32) UNIQUE,merchant_name VARCHAR(128),merchant_category VARCHAR(64),city VARCHAR(64)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4",
    "CREATE TABLE IF NOT EXISTS transactions(id INT PRIMARY KEY,txn_no VARCHAR(32) UNIQUE,account_id INT,merchant_id INT NULL,txn_type VARCHAR(32),amount DECIMAL(18,2),currency VARCHAR(16),txn_time DATETIME,txn_status VARCHAR(32),channel VARCHAR(32),FOREIGN KEY(account_id) REFERENCES accounts(id),FOREIGN KEY(merchant_id) REFERENCES merchants(id)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4",
    "CREATE TABLE IF NOT EXISTS loan_products(id INT PRIMARY KEY,product_code VARCHAR(32) UNIQUE,product_name VARCHAR(128),loan_type VARCHAR(32),annual_rate DECIMAL(10,4),tenor_months INT) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4",
    "CREATE TABLE IF NOT EXISTS loans(id INT PRIMARY KEY,loan_no VARCHAR(32) UNIQUE,customer_id INT,branch_id INT,product_id INT,principal_amount DECIMAL(18,2),outstanding_amount DECIMAL(18,2),loan_status VARCHAR(32),disbursed_at DATETIME,maturity_date DATE,FOREIGN KEY(customer_id) REFERENCES customers(id),FOREIGN KEY(branch_id) REFERENCES branches(id),FOREIGN KEY(product_id) REFERENCES loan_products(id)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4",
    "CREATE TABLE IF NOT EXISTS loan_repayment_plans(id INT PRIMARY KEY,loan_id INT,installment_no INT,due_date DATE,principal_due DECIMAL(18,2),interest_due DECIMAL(18,2),plan_status VARCHAR(32),FOREIGN KEY(loan_id) REFERENCES loans(id)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4",
    "CREATE TABLE IF NOT EXISTS repayments(id INT PRIMARY KEY,repayment_no VARCHAR(32) UNIQUE,loan_id INT,installment_no INT,paid_amount DECIMAL(18,2),paid_at DATETIME,channel VARCHAR(32),repayment_status VARCHAR(32),FOREIGN KEY(loan_id) REFERENCES loans(id)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4",
    "CREATE TABLE IF NOT EXISTS credit_cards(id INT PRIMARY KEY,card_no VARCHAR(32) UNIQUE,customer_id INT,branch_id INT,credit_limit DECIMAL(18,2),available_limit DECIMAL(18,2),card_status VARCHAR(32),issued_at DATETIME,FOREIGN KEY(customer_id) REFERENCES customers(id),FOREIGN KEY(branch_id) REFERENCES branches(id)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4",
    "CREATE TABLE IF NOT EXISTS card_transactions(id INT PRIMARY KEY,txn_no VARCHAR(32) UNIQUE,card_id INT,merchant_id INT,txn_amount DECIMAL(18,2),txn_time DATETIME,txn_type VARCHAR(32),txn_status VARCHAR(32),FOREIGN KEY(card_id) REFERENCES credit_cards(id),FOREIGN KEY(merchant_id) REFERENCES merchants(id)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4",
    "CREATE TABLE IF NOT EXISTS investment_products(id INT PRIMARY KEY,product_code VARCHAR(32) UNIQUE,product_name VARCHAR(128),product_type VARCHAR(32),risk_level VARCHAR(32),currency VARCHAR(16)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4",
    "CREATE TABLE IF NOT EXISTS customer_holdings(id INT PRIMARY KEY,customer_id INT,product_id INT,holding_units DECIMAL(18,4),market_value DECIMAL(18,2),holding_date DATE,FOREIGN KEY(customer_id) REFERENCES customers(id),FOREIGN KEY(product_id) REFERENCES investment_products(id)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4",
    "CREATE TABLE IF NOT EXISTS market_quotes(id INT PRIMARY KEY,product_id INT,quote_date DATE,nav DECIMAL(18,4),close_price DECIMAL(18,4),FOREIGN KEY(product_id) REFERENCES investment_products(id)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4",
    "CREATE TABLE IF NOT EXISTS insurance_policies(id INT PRIMARY KEY,policy_no VARCHAR(32) UNIQUE,customer_id INT,product_name VARCHAR(128),premium_amount DECIMAL(18,2),policy_status VARCHAR(32),start_date DATE,end_date DATE,FOREIGN KEY(customer_id) REFERENCES customers(id)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4",
    "CREATE TABLE IF NOT EXISTS policy_claims(id INT PRIMARY KEY,claim_no VARCHAR(32) UNIQUE,policy_id INT,claim_amount DECIMAL(18,2),claim_status VARCHAR(32),filed_at DATETIME,settled_at DATETIME NULL,FOREIGN KEY(policy_id) REFERENCES insurance_policies(id)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4",
    "CREATE TABLE IF NOT EXISTS aml_alerts(id INT PRIMARY KEY,alert_no VARCHAR(32) UNIQUE,customer_id INT,account_id INT NULL,alert_type VARCHAR(64),risk_level VARCHAR(32),status VARCHAR(32),created_at DATETIME,FOREIGN KEY(customer_id) REFERENCES customers(id),FOREIGN KEY(account_id) REFERENCES accounts(id)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4",
]

SEED = {
    "branches": [(1, "BJ001", "北京金融街支行", "北京", "华北", "2024-01-01 09:00:00"), (2, "SH001", "上海陆家嘴支行", "上海", "华东", "2024-01-01 09:00:00"), (3, "SZ001", "深圳前海支行", "深圳", "华南", "2024-01-01 09:00:00")],
    "employees": [(1, "E1001", 1, "张晨", "客户经理", "2020-03-01"), (2, "E1002", 1, "李倩", "风控经理", "2019-07-15"), (3, "E2001", 2, "王浩", "客户经理", "2021-04-12"), (4, "E3001", 3, "赵琳", "财富顾问", "2022-06-18")],
    "customers": [(1, "C0001", "华夏智投有限公司", "corporate", "91110101MA0001", "13800000001", "vip", 1, 1, "2023-01-10 10:00:00"), (2, "C0002", "刘欣", "retail", "110101199001010021", "13800000002", "mass_affluent", 1, 1, "2023-02-12 10:00:00"), (3, "C0003", "上海远航科技", "corporate", "91310000MA0002", "13800000003", "corporate", 2, 3, "2023-03-05 10:00:00"), (4, "C0004", "周洋", "retail", "440301199305050033", "13800000004", "vip", 3, 4, "2023-06-15 10:00:00")],
    "customer_contacts": [(1, 1, "email", "finance@huaxia.com", 1), (2, 2, "email", "liuxin@example.com", 1), (3, 3, "email", "ops@yuanhang.com", 1), (4, 4, "email", "zhouyang@example.com", 1)],
    "kyc_profiles": [(1, 1, "approved", 0, "1000w+", "2024-01-10 10:00:00"), (2, 2, "approved", 0, "50-100w", "2024-01-10 10:00:00"), (3, 3, "approved", 0, "1000w+", "2024-01-10 10:00:00"), (4, 4, "approved", 1, "100-300w", "2024-01-10 10:00:00")],
    "risk_profiles": [(1, 1, 72.5, "medium", 90, "2024-01-15 10:00:00"), (2, 2, 48.0, "low", 180, "2024-01-15 10:00:00"), (3, 3, 81.2, "high", 60, "2024-01-15 10:00:00"), (4, 4, 88.0, "high", 30, "2024-01-15 10:00:00")],
    "credit_scores": [(1, 1, "央行征信", "2024-01-20", 760, "A"), (2, 2, "央行征信", "2024-01-20", 690, "B"), (3, 3, "央行征信", "2024-01-20", 720, "A"), (4, 4, "央行征信", "2024-01-20", 670, "B")],
    "deposit_products": [(1, "D001", "活期存款", "demand", 0.3500, "CNY"), (2, "D002", "三年定期", "time_deposit", 2.8500, "CNY"), (3, "D003", "美元活期", "demand", 0.2500, "USD")],
    "accounts": [(1, "A0001", 1, 1, 1, "CNY", "active", "2023-01-12 10:00:00"), (2, "A0002", 1, 1, 2, "CNY", "active", "2023-01-12 10:00:00"), (3, "A0003", 2, 1, 1, "CNY", "active", "2023-02-15 10:00:00"), (4, "A0004", 3, 2, 1, "CNY", "active", "2023-03-08 10:00:00"), (5, "A0005", 4, 3, 1, "CNY", "active", "2023-06-18 10:00:00")],
    "account_daily_balances": [(1, 1, "2025-03-20", 1520000.00, 1518000.00), (2, 2, "2025-03-20", 8000000.00, 8000000.00), (3, 3, "2025-03-20", 185000.00, 184500.00), (4, 4, "2025-03-20", 5200000.00, 5190000.00), (5, 5, "2025-03-20", 420000.00, 419000.00)],
    "merchants": [(1, "M001", "东方证券商城", "investment", "上海"), (2, "M002", "国贸酒店", "travel", "北京"), (3, "M003", "云支付科技", "payment", "杭州")],
    "transactions": [(1, "T0001", 1, 2, "debit", 12800.00, "CNY", "2025-03-01 10:20:00", "success", "mobile"), (2, "T0002", 1, 3, "credit", 350000.00, "CNY", "2025-03-02 14:00:00", "success", "counter"), (3, "T0003", 3, 2, "debit", 5600.00, "CNY", "2025-03-02 17:35:00", "success", "mobile"), (4, "T0004", 4, 1, "debit", 880000.00, "CNY", "2025-03-03 09:00:00", "success", "online"), (5, "T0005", 5, None, "debit", 3200.00, "CNY", "2025-03-04 16:10:00", "success", "atm")],
    "loan_products": [(1, "L001", "流动资金贷款", "corporate", 4.3500, 12), (2, "L002", "个人消费贷", "retail", 5.8800, 24), (3, "L003", "供应链融资", "corporate", 4.9500, 6)],
    "loans": [(1, "LN0001", 1, 1, 1, 5000000.00, 3200000.00, "normal", "2024-01-01 10:00:00", "2025-12-31"), (2, "LN0002", 2, 1, 2, 300000.00, 180000.00, "normal", "2024-06-01 10:00:00", "2026-05-31"), (3, "LN0003", 3, 2, 3, 8000000.00, 4100000.00, "overdue", "2024-02-15 10:00:00", "2025-08-15")],
    "loan_repayment_plans": [(1, 1, 1, "2025-03-15", 300000.00, 18000.00, "paid"), (2, 1, 2, "2025-04-15", 300000.00, 16500.00, "due"), (3, 3, 1, "2025-03-10", 500000.00, 33000.00, "overdue")],
    "repayments": [(1, "RP0001", 1, 1, 318000.00, "2025-03-15 11:00:00", "counter", "success"), (2, "RP0002", 2, 1, 14200.00, "2025-03-18 12:00:00", "mobile", "success")],
    "credit_cards": [(1, "CC0001", 2, 1, 80000.00, 56000.00, "active", "2024-01-10 10:00:00"), (2, "CC0002", 4, 3, 150000.00, 90000.00, "active", "2024-04-01 10:00:00")],
    "card_transactions": [(1, "CT0001", 1, 2, 6800.00, "2025-03-02 20:00:00", "消费", "success"), (2, "CT0002", 1, 3, 12000.00, "2025-03-05 14:10:00", "消费", "success"), (3, "CT0003", 2, 1, 25000.00, "2025-03-08 16:40:00", "投资", "success")],
    "investment_products": [(1, "I001", "稳健债券基金", "fund", "low", "CNY"), (2, "I002", "科技成长基金", "fund", "high", "CNY"), (3, "I003", "美元固收产品", "bond", "medium", "USD")],
    "customer_holdings": [(1, 1, 1, 100000.0000, 1025000.00, "2025-03-20"), (2, 1, 2, 35000.0000, 880000.00, "2025-03-20"), (3, 4, 3, 15000.0000, 156000.00, "2025-03-20")],
    "market_quotes": [(1, 1, "2025-03-20", 10.2500, 10.2500), (2, 2, "2025-03-20", 25.0000, 25.0000), (3, 3, "2025-03-20", 10.4000, 10.4000)],
    "insurance_policies": [(1, "P0001", 2, "家庭医疗险", 6800.00, "active", "2024-01-01", "2025-12-31"), (2, "P0002", 4, "高端重疾险", 12500.00, "active", "2024-06-01", "2034-05-31")],
    "policy_claims": [(1, "CL0001", 1, 12000.00, "processing", "2025-03-05 10:00:00", None), (2, "CL0002", 2, 86000.00, "settled", "2025-02-15 10:00:00", "2025-03-01 10:00:00")],
    "aml_alerts": [(1, "AML0001", 1, 2, "大额频繁转入", "medium", "open", "2025-03-06 10:00:00"), (2, "AML0002", 3, 4, "跨境异常交易", "high", "investigating", "2025-03-07 10:00:00"), (3, "AML0003", 4, 5, "高风险客户大额消费", "high", "open", "2025-03-08 10:00:00")],
}

EXTRA_SEED = {
    "customers": [(5, "C0005", "深圳恒盛贸易", "corporate", "91440300MA0003", "13800000005", "corporate", 3, 4, "2023-07-10 10:00:00"), (6, "C0006", "孙悦", "retail", "110101198812120044", "13800000006", "mass_affluent", 1, 2, "2023-08-11 10:00:00"), (7, "C0007", "鹏程资本管理", "corporate", "91440300MA0004", "13800000007", "vip", 3, 4, "2023-09-12 10:00:00"), (8, "C0008", "陈诺", "retail", "310101199202020022", "13800000008", "mass", 2, 3, "2023-10-13 10:00:00"), (9, "C0009", "嘉禾资产配置", "corporate", "91310000MA0005", "13800000009", "vip", 2, 3, "2023-11-14 10:00:00"), (10, "C0010", "林岚", "retail", "440301199001010099", "13800000010", "vip", 3, 4, "2023-12-15 10:00:00")],
    "customer_contacts": [(5, 5, "email", "trade@hengsheng.com", 1), (6, 6, "email", "sunyue@example.com", 1), (7, 7, "email", "ir@pengchengcap.com", 1), (8, 8, "email", "chennuo@example.com", 1), (9, 9, "email", "ops@jiahe.com", 1), (10, 10, "email", "linlan@example.com", 1)],
    "kyc_profiles": [(5, 5, "approved", 0, "500-1000w", "2024-02-10 10:00:00"), (6, 6, "approved", 0, "50-100w", "2024-02-10 10:00:00"), (7, 7, "approved", 0, "1000w+", "2024-02-10 10:00:00"), (8, 8, "pending_review", 0, "20-50w", "2024-02-10 10:00:00"), (9, 9, "approved", 0, "1000w+", "2024-02-10 10:00:00"), (10, 10, "approved", 1, "100-300w", "2024-02-10 10:00:00")],
    "risk_profiles": [(5, 5, 68.5, "medium", 90, "2024-02-15 10:00:00"), (6, 6, 52.0, "low", 180, "2024-02-15 10:00:00"), (7, 7, 79.0, "high", 60, "2024-02-15 10:00:00"), (8, 8, 55.0, "medium", 90, "2024-02-15 10:00:00"), (9, 9, 83.0, "high", 60, "2024-02-15 10:00:00"), (10, 10, 86.0, "high", 30, "2024-02-15 10:00:00")],
    "credit_scores": [(5, 5, "央行征信", "2024-02-20", 710, "A"), (6, 6, "央行征信", "2024-02-20", 655, "C"), (7, 7, "央行征信", "2024-02-20", 735, "A"), (8, 8, "央行征信", "2024-02-20", 640, "C"), (9, 9, "央行征信", "2024-02-20", 750, "A"), (10, 10, "央行征信", "2024-02-20", 680, "B")],
    "accounts": [(6, "A0006", 5, 3, 2, "CNY", "active", "2023-07-10 10:00:00"), (7, "A0007", 6, 1, 1, "CNY", "active", "2023-08-11 10:00:00"), (8, "A0008", 7, 3, 1, "CNY", "active", "2023-09-12 10:00:00"), (9, "A0009", 9, 2, 1, "CNY", "active", "2023-11-14 10:00:00"), (10, "A0010", 10, 3, 3, "USD", "active", "2023-12-15 10:00:00")],
    "account_daily_balances": [(6, 6, "2025-03-20", 2800000.00, 2795000.00), (7, 7, "2025-03-20", 210000.00, 208000.00), (8, 8, "2025-03-20", 12000000.00, 11980000.00), (9, 9, "2025-03-20", 5200000.00, 5180000.00), (10, 10, "2025-03-20", 950000.00, 948000.00)],
    "transactions": [(6, "T0006", 6, 3, "credit", 1200000.00, "CNY", "2025-03-03 11:20:00", "success", "counter"), (7, "T0007", 7, 3, "debit", 2300.00, "CNY", "2025-03-05 19:20:00", "success", "mobile"), (8, "T0008", 8, 1, "credit", 2600000.00, "CNY", "2025-03-06 08:00:00", "success", "counter"), (9, "T0009", 9, 1, "debit", 120000.00, "CNY", "2025-03-06 12:30:00", "success", "online"), (10, "T0010", 10, 2, "debit", 12000.00, "USD", "2025-03-07 13:00:00", "success", "online"), (11, "T0011", 6, 2, "debit", 86000.00, "CNY", "2025-03-08 16:10:00", "success", "mobile"), (12, "T0012", 8, 3, "credit", 5000000.00, "CNY", "2025-03-09 09:30:00", "success", "counter")],
    "loans": [(4, "LN0004", 5, 3, 1, 4500000.00, 2600000.00, "normal", "2024-03-20 10:00:00", "2026-03-19"), (5, "LN0005", 7, 3, 3, 9500000.00, 7200000.00, "normal", "2024-05-18 10:00:00", "2025-11-18"), (6, "LN0006", 9, 2, 1, 6200000.00, 6200000.00, "watchlist", "2024-07-08 10:00:00", "2026-07-08")],
    "loan_repayment_plans": [(4, 4, 1, "2025-03-22", 260000.00, 21000.00, "due"), (5, 5, 1, "2025-03-25", 420000.00, 39000.00, "due"), (6, 6, 1, "2025-03-28", 360000.00, 28000.00, "watchlist")],
    "credit_cards": [(3, "CC0003", 6, 1, 100000.00, 76000.00, "active", "2024-05-01 10:00:00"), (4, "CC0004", 8, 2, 50000.00, 18000.00, "active", "2024-06-01 10:00:00"), (5, "CC0005", 10, 3, 180000.00, 150000.00, "active", "2024-08-01 10:00:00")],
    "card_transactions": [(4, "CT0004", 3, 1, 25000.00, "2025-03-08 16:40:00", "投资", "success"), (5, "CT0005", 4, 2, 18800.00, "2025-03-09 12:30:00", "旅行", "success"), (6, "CT0006", 5, 3, 68000.00, "2025-03-10 14:45:00", "企业采购", "success")],
    "customer_holdings": [(4, 5, 1, 60000.0000, 615000.00, "2025-03-20"), (5, 7, 2, 98000.0000, 2450000.00, "2025-03-20"), (6, 10, 3, 15000.0000, 156000.00, "2025-03-20")],
    "insurance_policies": [(3, "P0003", 5, "企业财产险", 58000.00, "active", "2024-03-01", "2026-02-28"), (4, "P0004", 10, "高端住院险", 9600.00, "active", "2024-08-01", "2025-07-31")],
    "policy_claims": [(3, "CL0003", 3, 230000.00, "processing", "2025-03-09 15:00:00", None), (4, "CL0004", 4, 28000.00, "reviewing", "2025-03-10 10:00:00", None)],
    "aml_alerts": [(4, "AML0004", 7, 8, "对公客户集中收款", "medium", "open", "2025-03-09 11:00:00"), (5, "AML0005", 10, 10, "高风险外币交易", "high", "investigating", "2025-03-10 11:00:00")],
}

MORE_SQL_ASSETS = [
    ("分支客户资产分层看板", "统计各支行 VIP 与普通客户的账户余额分层情况", {"sql_template": "SELECT b.name AS branch_name,c.segment,COUNT(DISTINCT c.id) AS customer_count,SUM(adb.end_balance) AS total_balance FROM branches b JOIN customers c ON c.branch_id=b.id JOIN accounts a ON a.customer_id=c.id JOIN account_daily_balances adb ON adb.account_id=a.id WHERE adb.balance_date=:balance_date GROUP BY b.name,c.segment ORDER BY total_balance DESC;", "sql_kind": "select", "table_names": ["branches", "customers", "accounts", "account_daily_balances"], "tags": ["支行", "客户分层", "余额统计"], "parameter_schema": {"balance_date": "余额日期"}}),
    ("企业客户存贷交叉分析", "查看企业客户的存款余额与贷款余额交叉情况", {"sql_template": "SELECT c.customer_no,c.name AS customer_name,SUM(adb.end_balance) AS total_deposit,SUM(l.outstanding_amount) AS total_loan FROM customers c JOIN accounts a ON a.customer_id=c.id JOIN account_daily_balances adb ON adb.account_id=a.id JOIN loans l ON l.customer_id=c.id WHERE c.customer_type='corporate' AND adb.balance_date=:balance_date GROUP BY c.customer_no,c.name ORDER BY total_loan DESC;", "sql_kind": "select", "table_names": ["customers", "accounts", "account_daily_balances", "loans"], "tags": ["企业客户", "存贷分析"], "parameter_schema": {"balance_date": "余额日期"}}),
    ("高风险客户交易预警视图", "联查风险画像、账户流水和 AML 预警，定位高风险客户交易", {"sql_template": "SELECT c.customer_no,c.name AS customer_name,r.risk_level,t.txn_no,t.amount,t.txn_time,a.alert_no,a.alert_type FROM customers c JOIN risk_profiles r ON r.customer_id=c.id JOIN accounts acc ON acc.customer_id=c.id JOIN transactions t ON t.account_id=acc.id LEFT JOIN aml_alerts a ON a.customer_id=c.id WHERE r.risk_level='high' AND t.txn_time>=:start_time ORDER BY t.amount DESC LIMIT 100;", "sql_kind": "select", "table_names": ["customers", "risk_profiles", "accounts", "transactions", "aml_alerts"], "tags": ["高风险客户", "交易预警", "AML"], "parameter_schema": {"start_time": "开始时间"}}),
    ("信用卡与贷款关联敞口", "分析客户信用卡额度与贷款余额的综合敞口", {"sql_template": "SELECT c.customer_no,c.name AS customer_name,SUM(cc.credit_limit-cc.available_limit) AS card_used_limit,SUM(l.outstanding_amount) AS loan_outstanding FROM customers c JOIN credit_cards cc ON cc.customer_id=c.id LEFT JOIN loans l ON l.customer_id=c.id GROUP BY c.customer_no,c.name ORDER BY loan_outstanding DESC;", "sql_kind": "select", "table_names": ["customers", "credit_cards", "loans"], "tags": ["信用卡", "贷款", "敞口"], "parameter_schema": {}}),
    ("保单理赔与客户风险联合视图", "查看理赔处理中客户的风险等级和保单情况", {"sql_template": "SELECT c.customer_no,c.name AS customer_name,p.policy_no,p.product_name,cl.claim_no,cl.claim_status,r.risk_level FROM customers c JOIN insurance_policies p ON p.customer_id=c.id JOIN policy_claims cl ON cl.policy_id=p.id LEFT JOIN risk_profiles r ON r.customer_id=c.id WHERE cl.claim_status IN ('processing','reviewing') ORDER BY cl.filed_at DESC;", "sql_kind": "select", "table_names": ["customers", "insurance_policies", "policy_claims", "risk_profiles"], "tags": ["保单", "理赔", "风险等级"], "parameter_schema": {}}),
    ("客户投资与存款组合分析", "对比客户投资持仓市值与存款余额", {"sql_template": "SELECT c.customer_no,c.name AS customer_name,SUM(h.market_value) AS investment_value,SUM(adb.end_balance) AS deposit_value FROM customers c JOIN customer_holdings h ON h.customer_id=c.id JOIN accounts a ON a.customer_id=c.id JOIN account_daily_balances adb ON adb.account_id=a.id WHERE h.holding_date=:holding_date AND adb.balance_date=:balance_date GROUP BY c.customer_no,c.name ORDER BY investment_value DESC;", "sql_kind": "select", "table_names": ["customers", "customer_holdings", "accounts", "account_daily_balances"], "tags": ["投资", "存款", "组合分析"], "parameter_schema": {"holding_date": "持仓日期", "balance_date": "余额日期"}}),
]


def run_mysql():
    conn = pymysql.connect(charset="utf8mb4", autocommit=True, **MYSQL)
    try:
        cur = conn.cursor()
        cur.execute(f"CREATE DATABASE IF NOT EXISTS `{MYSQL_DB}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
        cur.execute(f"USE `{MYSQL_DB}`")
        for ddl in DDL:
            cur.execute(ddl)
        for table, rows in SEED.items():
            placeholders = ",".join(["%s"] * len(rows[0]))
            cur.executemany(f"INSERT IGNORE INTO {table} VALUES ({placeholders})", rows)
        for table, rows in EXTRA_SEED.items():
            placeholders = ",".join(["%s"] * len(rows[0]))
            cur.executemany(f"INSERT IGNORE INTO {table} VALUES ({placeholders})", rows)
        cur.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema=%s", (MYSQL_DB,))
        table_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM customers")
        customer_count = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM transactions")
        txn_count = cur.fetchone()[0]
        print(f"MySQL库 {MYSQL_DB} 已就绪：表 {table_count} 张，客户 {customer_count} 条，流水 {txn_count} 条")
    finally:
        conn.close()


def run_sqlite():
    from xagent.web.models.database import get_db, init_db
    from xagent.web.models.biz_system import BizSystem
    from xagent.web.models.datamakepool_asset import DataMakepoolAsset
    from xagent.web.models.text2sql import DatabaseStatus, DatabaseType, Text2SQLDatabase
    from xagent.web.models.user import User, UserSystemBinding
    from xagent.datamakepool.assets.repositories import HttpAssetRepository, SqlAssetRepository

    init_db(SQLITE_URL)
    db = next(get_db())
    try:
        def get_or_create_system(short: str, name: str):
            row = db.query(BizSystem).filter(BizSystem.system_short == short).first()
            if row is None:
                row = BizSystem(system_short=short, system_name=name)
                db.add(row)
                db.flush()
            return row

        fin = get_or_create_system("fin", "金融测试系统")
        xagent = get_or_create_system("xagent", "XAgent联调系统")
        admins = db.query(User).filter(User.is_admin.is_(True)).all()
        if not admins:
            first = db.query(User).order_by(User.id.asc()).first()
            admins = [first] if first else []
        for user in admins:
            if user is None:
                continue
            for system in (fin, xagent):
                binding = db.query(UserSystemBinding).filter(UserSystemBinding.user_id == user.id, UserSystemBinding.system_id == system.id).first()
                if binding is None:
                    db.add(UserSystemBinding(user_id=user.id, system_id=system.id, binding_role="system_admin", source="manual", is_active=True))
        owner_id = int(admins[0].id) if admins else None
        db.flush()

        mysql_url = f"mysql+pymysql://{MYSQL['user']}:{MYSQL['password']}@{MYSQL['host']}:{MYSQL['port']}/{MYSQL_DB}"
        row = db.query(Text2SQLDatabase).filter(Text2SQLDatabase.name == "fin-mysql-main").first()
        if row is None:
            row = Text2SQLDatabase(user_id=owner_id or 1, name="fin-mysql-main", system_id=fin.id, type=DatabaseType.MYSQL, url=mysql_url, read_only=True, enabled=True, status=DatabaseStatus.CONNECTED, table_count=len(DDL), last_connected_at=datetime.utcnow(), error_message=None)
            db.add(row)
            db.flush()
        else:
            row.system_id = fin.id
            row.type = DatabaseType.MYSQL
            row.url = mysql_url
            row.read_only = True
            row.enabled = True
            row.status = DatabaseStatus.CONNECTED
            row.table_count = len(DDL)
            row.last_connected_at = datetime.utcnow()
            row.error_message = None
            db.flush()

        sql_repo = SqlAssetRepository(db)
        datasource = sql_repo.upsert_datasource_asset_from_text2sql_database(row, updated_by=owner_id)
        http_repo = HttpAssetRepository(db)

        def upsert_sql(name: str, description: str, config: dict):
            existing = db.query(DataMakepoolAsset).filter(DataMakepoolAsset.asset_type == "sql", DataMakepoolAsset.system_short == "fin", DataMakepoolAsset.name == name).first()
            payload = dict(name=name, system_short="fin", description=description, status="active", sensitivity_level="medium", datasource_asset_id=int(datasource.id), config=config, updated_by=owner_id)
            if existing is None:
                sql_repo.create_sql_asset({**payload, "created_by": owner_id})
            else:
                sql_repo.update_sql_asset(existing, payload)

        def upsert_http(name: str, system_short: str, description: str, config: dict):
            existing = db.query(DataMakepoolAsset).filter(DataMakepoolAsset.asset_type == "http", DataMakepoolAsset.system_short == system_short, DataMakepoolAsset.name == name).first()
            payload = dict(name=name, system_short=system_short, description=description, status="active", sensitivity_level="low", config=config, updated_by=owner_id)
            if existing is None:
                http_repo.create_http_asset({**payload, "created_by": owner_id})
            else:
                http_repo.update_http_asset(existing, payload)

        sql_assets = [
            ("客户账户资产总览", "查询客户在账户、支行和产品下的资产总览", {"sql_template": "SELECT c.customer_no,c.name AS customer_name,a.account_no,p.product_name,b.name AS branch_name,adb.end_balance FROM customers c JOIN accounts a ON a.customer_id=c.id JOIN deposit_products p ON p.id=a.product_id JOIN branches b ON b.id=a.branch_id LEFT JOIN account_daily_balances adb ON adb.account_id=a.id WHERE c.customer_no=:customer_no ORDER BY adb.balance_date DESC LIMIT 20;", "sql_kind": "select", "table_names": ["customers", "accounts", "deposit_products", "branches", "account_daily_balances"], "tags": ["客户", "账户", "资产总览", "余额"], "parameter_schema": {"customer_no": "客户编号"}}),
            ("近30天账户流水查询", "查询指定账户近30天交易流水及商户信息", {"sql_template": "SELECT a.account_no,t.txn_no,t.txn_type,t.amount,t.txn_time,t.channel,m.merchant_name FROM accounts a JOIN transactions t ON t.account_id=a.id LEFT JOIN merchants m ON m.id=t.merchant_id WHERE a.account_no=:account_no AND t.txn_time>=:start_time ORDER BY t.txn_time DESC LIMIT 100;", "sql_kind": "select", "table_names": ["accounts", "transactions", "merchants"], "tags": ["流水", "交易", "商户", "账户"], "parameter_schema": {"account_no": "账号", "start_time": "开始时间"}}),
            ("贷款逾期监控清单", "查询逾期贷款及客户、支行、还款计划信息", {"sql_template": "SELECT l.loan_no,c.name AS customer_name,b.name AS branch_name,rp.installment_no,rp.due_date,rp.principal_due,rp.interest_due FROM loans l JOIN customers c ON c.id=l.customer_id JOIN branches b ON b.id=l.branch_id JOIN loan_repayment_plans rp ON rp.loan_id=l.id WHERE l.loan_status='overdue' OR rp.plan_status='overdue' ORDER BY rp.due_date ASC;", "sql_kind": "select", "table_names": ["loans", "customers", "branches", "loan_repayment_plans"], "tags": ["贷款", "逾期", "还款计划"], "parameter_schema": {}}),
            ("信用卡大额消费分析", "查询高净值客户信用卡大额消费与商户分布", {"sql_template": "SELECT c.name AS customer_name,cc.card_no,ct.txn_no,ct.txn_amount,ct.txn_time,m.merchant_name,m.merchant_category FROM credit_cards cc JOIN customers c ON c.id=cc.customer_id JOIN card_transactions ct ON ct.card_id=cc.id JOIN merchants m ON m.id=ct.merchant_id WHERE ct.txn_amount>=:min_amount ORDER BY ct.txn_amount DESC LIMIT 50;", "sql_kind": "select", "table_names": ["credit_cards", "customers", "card_transactions", "merchants"], "tags": ["信用卡", "大额消费", "商户"], "parameter_schema": {"min_amount": "最小交易金额"}}),
            ("客户投资持仓概览", "查询客户投资持仓、产品和最新行情", {"sql_template": "SELECT c.name AS customer_name,p.product_name,p.product_type,h.holding_units,h.market_value,q.nav,q.close_price FROM customer_holdings h JOIN customers c ON c.id=h.customer_id JOIN investment_products p ON p.id=h.product_id LEFT JOIN market_quotes q ON q.product_id=p.id AND q.quote_date=:quote_date WHERE c.customer_no=:customer_no ORDER BY h.market_value DESC;", "sql_kind": "select", "table_names": ["customer_holdings", "customers", "investment_products", "market_quotes"], "tags": ["投资", "持仓", "行情"], "parameter_schema": {"customer_no": "客户编号", "quote_date": "行情日期"}}),
            ("客户综合风险画像", "查询客户KYC、风险评分和征信评分的综合画像", {"sql_template": "SELECT c.customer_no,c.name AS customer_name,k.kyc_status,k.pep_flag,r.risk_score,r.risk_level,cs.credit_score,cs.score_rating FROM customers c LEFT JOIN kyc_profiles k ON k.customer_id=c.id LEFT JOIN risk_profiles r ON r.customer_id=c.id LEFT JOIN credit_scores cs ON cs.customer_id=c.id WHERE c.customer_no=:customer_no ORDER BY cs.score_date DESC LIMIT 5;", "sql_kind": "select", "table_names": ["customers", "kyc_profiles", "risk_profiles", "credit_scores"], "tags": ["客户画像", "KYC", "征信", "风险评分"], "parameter_schema": {"customer_no": "客户编号"}}),
        ]
        for name, description, config in sql_assets:
            upsert_sql(name, description, config)
        for name, description, config in MORE_SQL_ASSETS:
            upsert_sql(name, description, config)

        http_assets = [
            ("XAgent健康检查", "xagent", "联调 XAgent 后端健康检查接口", {"base_url": XAGENT_BASE_URL, "path_template": "/health", "method": "GET", "default_headers": {}, "query_params": {}, "response_extract": {"message_path": "status"}, "timeout": 10, "retry_count": 1}),
            ("XAgent初始化状态查询", "xagent", "联调 XAgent 管理员初始化状态接口", {"base_url": XAGENT_BASE_URL, "path_template": "/api/auth/setup-status", "method": "GET", "default_headers": {}, "query_params": {}, "response_extract": {"fields": {"needsSetup": "needs_setup"}}, "timeout": 10, "retry_count": 1}),
            ("XAgent数据库类型模板查询", "xagent", "联调 Text2SQL 数据库类型模板接口", {"base_url": XAGENT_BASE_URL, "path_template": "/api/text2sql/database-types", "method": "GET", "default_headers": {}, "query_params": {}, "response_extract": {"summary_template": "数据库类型模板列表已返回"}, "timeout": 10, "retry_count": 1}),
        ]
        for name, system_short, description, config in http_assets:
            upsert_http(name, system_short, description, config)

        db.commit()
        sql_count = db.query(DataMakepoolAsset).filter(DataMakepoolAsset.asset_type == "sql", DataMakepoolAsset.system_short == "fin").count()
        http_count = db.query(DataMakepoolAsset).filter(DataMakepoolAsset.asset_type == "http", DataMakepoolAsset.system_short == "xagent").count()
        ds_count = db.query(Text2SQLDatabase).filter(Text2SQLDatabase.name == "fin-mysql-main").count()
        print(f"SQLite库已写入：Text2SQL数据源 {ds_count} 条，SQL资产 {sql_count} 条，HTTP资产 {http_count} 条")
    finally:
        db.close()


if __name__ == "__main__":
    run_mysql()
    run_sqlite()
    print("全部初始化完成。")
