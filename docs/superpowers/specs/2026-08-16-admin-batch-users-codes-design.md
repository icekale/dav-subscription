# 用户与注册码批量管理

日期：2026-08-16  
范围：管理后台 `#/admin/users`、`#/admin/codes`

## 目标

管理员能在用户列表和注册码列表里勾选多条，用和大V列表相同的「表上方操作条」一次做完常见维护，不必逐条点开。

## 不做

- 批量改用户名、重置密码、设/取消管理员、批量测试推送
- 批量改注册码备注（单行备注保留）
- 底部固定操作条
- 前端循环打单条接口代替批量接口
- 把已用码的来源写进用户表（删已用码后，用户「来源」变为空）

## 交互（两边共用）

对齐现有大V列表（`#ak-batch-bar` / `_adminKolsSelected`）：

- 表格最左增加勾选列；表头勾选只作用于**当前筛选可见行**
- 勾选在切换筛选、搜索后保留；成功批量操作后清空
- 有选中时，筛选和表格之间出现操作条：已选 N · 动作按钮 · 取消选择
- 无选中时操作条 `display:none`，与大V的 `#ak-batch-bar` 相同
- 手机：操作条折行，按钮最小高度 44px
- 单条原有入口保留（用户「管理 / 测试推送」；注册码单行作废、备注、批次「复制未用 / 作废未用」）

## 用户页

操作条：开启推送 · 关闭推送 · 删除 · 取消选择。

- 删除：`confirm`，文案带数量；不能删自己（服务端跳过，toast「已删 n，跳过本人」）
- 开关推送：无 confirm，可包含自己；toast 报数量
- 行上「管理」弹窗不改

## 注册码页

生成栏不改。列表（搜索/状态 Tab）下方、分批表格上方出现操作条：复制 · 作废未用 · 清掉废码 · 取消选择。

- 每行勾选；批次标题勾选 = 勾/取消这一批**可见**行。该批可见行全部选中则标题勾选为 checked，部分选中则为 indeterminate
- **复制**：把选中码号按行拼接后写入剪贴板（与单码 `copyText(code)` 相同内容，多码换行），不打接口，不拼邀请文案
- **作废未用**：`confirm` 带数量；只作废未使用且未作废的（含未用已过期）。选中里没有可作废项时按钮禁用
- **清掉废码**：`confirm` 带数量；物理删除已用 / 已作废 / 已过期。选中里没有这类码时按钮禁用。可用码不能删
- 现有按批次「复制未用 / 作废未用」和单行备注、单行作废保留

## 接口

均需管理员。空 `ids` / `codes` → 400「请先选择…」。非管理员 → 403。成功后写 audit。

### `POST /api/admin/users/batch`

```json
{ "ids": [1, 2, 3], "action": "enable_notify" | "disable_notify" | "delete" }
```

- `enable_notify` / `disable_notify`：更新 `users.notify_enabled`（管理员批量路径今天还没有这个字段，只加在本接口，不改单人 `PUT /api/users/{id}`）
- `delete`：对每个 id 走与现有 `DELETE /api/users/{id}` 相同的级联删除；`id == 当前管理员` 或不存在的 id 记入 `skipped`，整单仍 200
- 响应：`{ "ok": true, "count": <实际处理数>, "skipped": <跳过数> }`
- 不支持的 `action` → 400

### `POST /api/admin/register-codes/batch`

```json
{ "codes": ["ABC12345", "..."], "action": "revoke" | "delete" }
```

- `revoke`：对每条调用与现有单条作废相同的条件（`used_by IS NULL AND revoked_at IS NULL`）。已用/已作废跳过。全部不合法 → 400
- `delete`：仅当状态为已用、已作废或已过期时 `DELETE FROM register_codes`。可用码跳过。全部不合法 → 400
- 现有 `db.delete_register_code` 实际是作废，不能复用；新增真正的物理删除
- 混选时处理合法项，响应带 `count` / `skipped`；不要为了几条不合法而整单失败（空结果除外）
- 删已用码不更新用户表；`GET /api/users` 的 `register_code` / `register_note` 下次即为空

复制不设接口。

## 数据与安全

- 物理删除注册码不可恢复；confirm 必须写清「从列表删除，不可恢复」
- 删除用户不可恢复，文案与现有单人删除一致（订阅一并清除）
- 勾选 id / code 写入 `dataset` 或受控集合，禁止把用户名、备注插进 `onclick` 字符串（沿用 `tests/test_frontend_xss.py`）
- 选择状态用 `Set`，与 `_adminKolsSelected` 同模式

## 前端缓存

`index.html` 的 `app.js` / `style.css` 查询参数 +1；`sw.js` 的 `CACHE` 名 +1。不改产品版本号，除非同一次提交里已有版本变更。

## 测试

API（`tests/test_api.py`）：

- 用户：批量开启/关闭推送后列表字段变化；批量删除跳过本人、其余删除成功；普通用户 403
- 注册码：批量作废未用；批量删除已用/已作废/已过期；拒绝（跳过）可用码；删除已用码后对应用户来源为空

前端（`tests/test_frontend_interactions.py`）：

- 用户页、注册码页 markup 含勾选列与批量条 class / 动作文案
- 注册码批次标题有全选勾选

XSS：现有事件处理约束仍然通过。
