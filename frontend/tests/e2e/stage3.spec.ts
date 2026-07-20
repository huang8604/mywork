import { expect, test, type Page, type Route } from '@playwright/test'

const stats = { known_count: 3, unknown_count: 1, skipped_count: 1, total_attempts: 5, accuracy: .75, reviewed_words: 2, due_words: 1 }
const wordStats = { known_count: 0, unknown_count: 0, skipped_count: 0, total_attempts: 0, accuracy: null, consecutive_known: 0, consecutive_unknown: 0, last_status: null, last_reviewed_at: null, last_effective_status: null, last_effective_reviewed_at: null, interval_days: 0, due_at: null }
const word = { id: 1, en_word: 'serendipity', normalized_en_word: 'serendipity', phonetic: '/ˌserənˈdɪpəti/', cn_meaning: '意外发现美好事物的能力', example_sentence: 'A fortunate discovery.', is_custom: true, tags: ['灵感'], version: 1, created_at: '2026-07-20T01:00:00Z', updated_at: '2026-07-20T01:00:00Z', deleted_at: null, stats: wordStats }
const session = { session_id: 1, status: 'active', strategy_version: 'v1', seed: 7, strategy_params: {}, requested_counts: { new: 1 }, actual_counts: { new: 1 }, created_by_actor_type: 'api_client', created_by_actor_id: 'skill-1', skill_name: 'Family Review', skill_version: '1.0', version: 1, generated_at: '2026-07-20T01:00:00Z', printed_at: null, completed_at: null, archived_at: null, items: [{ item_id: 11, position: 1, word_id: 1, word: { en_word: word.en_word, phonetic: word.phonetic, cn_meaning: word.cn_meaning, example_sentence: word.example_sentence }, source_categories: ['new'], reason: 'new word', latest_review_log_id: null }], rounds: [] }
const envelope = <T>(data: T, meta: Record<string, unknown> = {}) => ({ code: 'OK', message: 'success', data, meta, request_id: 'e2e-request' })

async function installApi(page: Page) {
  const words = [word]
  await page.route('**/api/v1/**', async (route: Route) => {
    const request = route.request(); const url = new URL(request.url()); const path = url.pathname; const method = request.method()
    if (path === '/api/v1/stats/summary') return route.fulfill({ json: envelope(stats) })
    if (path === '/api/v1/practice-sessions' && method === 'GET') return route.fulfill({ json: envelope([session], { page: 1, size: 20, total: 1 }) })
    if (path === '/api/v1/practice-sessions/1' && method === 'GET') return route.fulfill({ json: envelope(session) })
    if (path === '/api/v1/practice-sessions/1/review-rounds') return route.fulfill({ status: 201, json: envelope({ round_id: 3, session_id: 1, mode: 'online', status: 'active', version: 1, started_at: '2026-07-20T02:00:00Z', completed_at: null, item_total: 1, answered_count: 0 }) })
    if (path === '/api/v1/practice-review-rounds/3/items/11/result') return route.fulfill({ status: 201, json: envelope({ id: 9, word_id: 1, session_item_id: 11, review_round_id: 3, status: JSON.parse(request.postData() || '{}').status, source: 'online_practice', actor_type: 'web_user', actor_id: 'local', client_event_id: JSON.parse(request.postData() || '{}').client_event_id, duration_ms: null, reviewed_at: '2026-07-20T02:00:00Z', version: 1, created_at: '2026-07-20T02:00:00Z', updated_at: '2026-07-20T02:00:00Z' }) })
    if (path === '/api/v1/reviews' && method === 'GET') return route.fulfill({ json: envelope([{ id: 9, word_id: 1, session_item_id: 11, review_round_id: 3, status: 'known', source: 'online_practice', actor_type: 'web_user', actor_id: 'local', client_event_id: 'event-9', duration_ms: null, reviewed_at: '2026-07-20T02:00:00Z', version: 1, created_at: '2026-07-20T02:00:00Z', updated_at: '2026-07-20T02:00:00Z' }], { page: 1, size: 20, total: 1 }) })
    if (path === '/api/v1/reviews/9' && method === 'PATCH') return route.fulfill({ json: envelope({ id: 9, word_id: 1, status: JSON.parse(request.postData() || '{}').status, source: 'online_practice', actor_type: 'web_user', client_event_id: 'event-9', reviewed_at: '2026-07-20T02:00:00Z', duration_ms: null, version: 2, created_at: '2026-07-20T02:00:00Z', updated_at: '2026-07-20T02:10:00Z', session_item_id: 11, review_round_id: 3, actor_id: 'local' }) })
    if (path === '/api/v1/words/import') return route.fulfill({ json: envelope({ created: 1, updated: 0, skipped: 0, rejected: 0, total: 1, dry_run: false }) })
    if (path === '/api/v1/words/export') return route.fulfill({ body: 'en_word,cn_meaning\nserendipity,意外发现', headers: { 'content-type': 'text/csv', 'content-disposition': 'attachment; filename="words.csv"' } })
    if (path === '/api/v1/words' && method === 'GET') return route.fulfill({ json: envelope(words, { page: 1, size: Number(url.searchParams.get('size') || 20), total: words.length }) })
    if (path === '/api/v1/words' && method === 'POST') { const body = JSON.parse(request.postData() || '{}'); const created = { ...word, ...body, id: 2 }; words.push(created); return route.fulfill({ status: 201, json: envelope(created) }) }
    if (path === '/api/v1/words/1' && method === 'GET') return route.fulfill({ json: envelope(word) })
    if (path === '/api/v1/words/1' && method === 'DELETE') return route.fulfill({ status: 204, body: '' })
    return route.fulfill({ status: 404, json: { code: 'NOT_FOUND', message: 'not found', details: [], request_id: 'e2e-404' } })
  })
}

test.beforeEach(async ({ page }) => installApi(page))

test('responsive dashboard and deep links never overflow the page', async ({ page }) => {
  await page.goto('/dashboard'); await expect(page.getByRole('heading', { name: '今日概览' })).toBeVisible()
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)
  expect(overflow).toBe(false)
  await page.goto('/does-not-exist'); await expect(page.getByRole('heading', { name: '这一页没有收录' })).toBeVisible()
})

test('keyboard focus and navigation targets meet accessibility basics', async ({ page }) => {
  await page.goto('/dashboard'); await page.locator('.skip-link').focus(); await expect(page.locator('.skip-link')).toBeFocused()
  await page.keyboard.press('Enter'); await expect(page.locator('#main-content')).toBeFocused()
  const targetHeights = await page.locator('.bottom-nav-item:visible, .nav-item:visible').evaluateAll((items) => items.map((item) => item.getBoundingClientRect().height))
  expect(targetHeights.length).toBeGreaterThan(0); expect(targetHeights.every((height) => height >= 44)).toBe(true)
  await page.goto('/review'); await page.getByRole('button', { name: '开始在线复习' }).click(); await page.keyboard.press('Space'); await expect(page.locator('.answer')).toBeFocused(); await page.keyboard.press('1'); await expect(page.locator('.status-live')).toBeFocused(); await expect(page.locator('.status-live')).toContainText('已保存：认识')
})

test('word CRUD form and atomic import summary remain usable', async ({ page }) => {
  const visibleWord = (text: string) => page.locator('.mobile-word-cards:visible h3, .desktop-word-table:visible .table-word').filter({ hasText: text })
  await page.goto('/words'); await expect(visibleWord('serendipity')).toBeVisible()
  await page.getByRole('button', { name: '新增单词' }).first().click(); await page.getByLabel('英文', { exact: true }).fill('resilient'); await page.getByLabel('中文释义', { exact: true }).fill('有韧性的'); await page.getByRole('button', { name: '保存' }).click(); await expect(visibleWord('resilient')).toBeVisible()
  await page.getByRole('button', { name: '导入 / 导出' }).click(); await page.locator('input[type=file]').setInputFiles({ name: 'words.csv', mimeType: 'text/csv', buffer: Buffer.from('en_word,cn_meaning\nfocus,专注') }); await page.getByRole('button', { name: '开始导入' }).click(); await expect(page.getByText('总计')).toBeVisible()
})

test('online review records three-state result and history permits correction', async ({ page }) => {
  await page.goto('/review'); await page.getByRole('button', { name: '开始在线复习' }).click(); await page.getByRole('button', { name: /显示答案/ }).click(); await page.getByRole('button', { name: /^认识/ }).click(); await expect(page.getByText(/已保存：认识/)).toBeVisible()
  await page.goto('/history'); await page.getByRole('button', { name: /认识.*修改|认识.*点按修改/ }).first().click(); await page.getByRole('button', { name: /^不认识/ }).first().click(); await expect(page.locator('.status-badge.unknown:visible')).toBeVisible()
})

test('external Skill session opens without exposing any token', async ({ page }) => {
  await page.goto('/daily/sessions/1'); await expect(page.getByText(/外部 Skill.*Family Review/)).toBeVisible(); await expect(page.locator('body')).not.toContainText('Bearer')
})
