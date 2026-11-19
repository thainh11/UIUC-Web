import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

const WIDTHS = [375, 768, 1024, 1440]

async function ready(page: Page, path = '/') {
  await page.goto(path)
  await expect(page.getByRole('heading', { name: 'Focus areas' })).toBeVisible()
  await expect(page.locator('#papers-summary')).toContainText(/\d papers/)
  await expect(page.getByRole('button', { name: /linked papers|No linked papers/ }).first()).toBeVisible()
}

for (const width of WIDTHS) {
  test(`no serious accessibility violations at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 })
    await ready(page)
    const { violations } = await new AxeBuilder({ page }).analyze()
    const bad = violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
    expect(bad.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`)).toEqual([])
  })
}

test('summary numbers carry the two-year window', async ({ page }) => {
  await ready(page)
  await expect(page.getByText('UIUC author profiles')).toBeVisible()
  await expect(page.getByText(/with linked papers/)).toBeVisible()
  await expect(page.getByText(/Nov 2024 – Nov 2026/).first()).toBeVisible()
})

test('field filter works from the mouse and keyboard, survives reload, and clears', async ({ page }) => {
  await ready(page)
  const first = page.locator('#topics').getByRole('button', { pressed: false }).first()
  const name = (await first.locator('span').first().innerText()).split('\n')[0]!
  await first.focus()
  await page.keyboard.press('Enter')
  await expect(page.locator('#papers-summary')).toContainText(`in ${name}`)
  await expect(page).toHaveURL(new RegExp(`field=${encodeURIComponent(name).replace(/%20/g, '(\\+|%20)')}`))
  await expect(page.locator('#papers-summary')).toBeFocused()

  await page.reload()
  await expect(page.locator('#papers-summary')).toContainText(`in ${name}`)
  await expect(page.locator('#topics').getByRole('button', { pressed: true })).toHaveCount(1)

  await page.locator('#topics').getByRole('button', { pressed: true }).click()
  await expect(page.locator('#papers-summary')).not.toContainText(`in ${name}`)
})

test('a slow old search never overwrites a newer one', async ({ page }) => {
  await ready(page)
  await page.route('**/api/papers?*query=aaa*', async (route) => {
    await new Promise((r) => setTimeout(r, 1500))
    await route.continue().catch(() => {})
  })
  const box = page.getByLabel('Search titles and abstracts')
  await box.fill('aaa')
  await page.waitForTimeout(450) // debounce fired, slow request in flight
  await box.fill('protein')
  await expect(page.locator('#papers-summary')).toContainText('matching “protein”')
  await page.waitForTimeout(1800)
  await expect(page.locator('#papers-summary')).toContainText('matching “protein”')
  await expect(page.getByLabel('Sort by')).toHaveValue('relevance')
})

test('no matches shows a way out', async ({ page }) => {
  await ready(page)
  await page.getByLabel('Search titles and abstracts').fill('zzzqqqxxx')
  await expect(page.getByText('No matches')).toBeVisible()
  await page.getByRole('button', { name: 'Clear filters' }).click()
  await expect(page.locator('#papers-summary')).toContainText(/\d papers/)
  await expect(page.getByLabel('Search titles and abstracts')).toHaveValue('')
})

test('a failing block shows its own error and the rest of the page still works', async ({ page }) => {
  await page.route('**/api/papers?*', (route) => route.fulfill({ status: 500, body: 'boom' }))
  await page.goto('/')
  await expect(page.getByRole('alert').filter({ hasText: 'Could not load papers.' })).toBeVisible()
  await expect(page.getByText('UIUC author profiles')).toBeVisible()
  await expect(page.getByRole('button', { name: /linked papers|No linked papers/ }).first()).toBeVisible()
  await page.unroute('**/api/papers?*')
  await page.getByRole('button', { name: 'Try again' }).click()
  await expect(page.locator('#papers-summary')).toContainText(/\d papers/)
})

test('faculty drawer opens, traps Esc, and returns focus to the card', async ({ page }) => {
  await ready(page)
  const card = page.getByRole('button', { name: /linked papers/ }).first()
  await card.click()
  const dialog = page.getByRole('dialog', { name: 'Faculty profile' })
  await expect(dialog).toBeVisible()
  await expect(dialog.getByRole('heading', { level: 3 })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
  await expect(card).toBeFocused()
})

test('unlinked faculty say so and show no papers', async ({ page }) => {
  // Faculty sort by linked papers, so the last page (1000 / 24 = 42 pages) holds unlinked people.
  await ready(page, '/?fpage=42')
  await page.getByRole('button', { name: /No linked papers yet/ }).first().click()
  const dialog = page.getByRole('dialog', { name: 'Faculty profile' })
  await expect(dialog.getByText('No papers could be matched to this person')).toBeVisible()
})

test('faculty photo that fails to load falls back to initials', async ({ page }) => {
  await page.route('**/*', (r) =>
    r.request().resourceType() === 'image' && !r.request().url().startsWith('http://127.0.0.1') ? r.abort() : r.continue(),
  )
  await ready(page)
  const card = page.getByRole('button', { name: /linked papers/ }).first()
  await card.scrollIntoViewIfNeeded() // images are lazy: they only load (and fail) once near the viewport
  await expect(card.locator('img')).toHaveCount(0)
  await expect(card.locator('span[aria-hidden="true"]').first()).toHaveText(/^[A-Z]{1,2}$/)
})

test('chat on a wide screen is a non-modal panel; Esc closes and focus returns', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await ready(page)
  const fab = page.getByRole('button', { name: 'Ask', exact: true })
  await fab.click()
  const dialog = page.getByRole('dialog', { name: 'Assistant' })
  await expect(dialog).toBeVisible()
  await expect(page.getByLabel('Ask about UIUC research')).toBeFocused()
  // Page behind stays interactive (non-modal).
  await page.getByLabel('Search titles and abstracts').fill('robot')
  await expect(page.locator('#papers-summary')).toContainText('matching “robot”')
  // Panel does not cover the sticky header.
  const box = await dialog.boundingBox()
  expect(box!.y).toBeGreaterThanOrEqual(64)
  await page.getByLabel('Ask about UIUC research').focus()
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
  await expect(fab).toBeFocused()
})

test('chat on a phone is a full-screen modal; Esc closes and focus returns', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 700 })
  await ready(page)
  const fab = page.getByRole('button', { name: 'Ask', exact: true })
  await fab.click()
  const dialog = page.getByRole('dialog', { name: 'Assistant' })
  await expect(dialog).toBeVisible()
  const box = await dialog.boundingBox()
  expect(box).toMatchObject({ x: 0, y: 0, width: 375, height: 700 })
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
  await expect(fab).toBeFocused()
})

const sse = (...events: [string, object][]) =>
  events.map(([type, data]) => `event: ${type}\ndata: ${JSON.stringify(data)}\n\n`).join('')

// The model is not part of these tests: the route replays the event stream the backend sends.
const reply = (body: string) => ({ status: 200, contentType: 'text/event-stream', body })

test('chat shows the answer with numbered citations, and a faculty citation opens the drawer', async ({ page, request }) => {
  const person = ((await (await request.get('/api/faculty?page_size=1')).json()) as { items: { id: number; name: string }[] }).items[0]!
  let sent: { message: string; history: unknown[] } | undefined
  await page.route('**/api/chat', (route) => {
    sent = route.request().postDataJSON()
    return route.fulfill(
      reply(
        sse(
          ['status', { tool: 'search_faculty', text: 'Searching faculty for “vision”' }],
          ['sources', { sources: [{ ref: 'F1', kind: 'faculty', label: person.name, facultyId: person.id }] }],
          ['delta', { text: `Best match:\n\n- **${person.name}** works on vision [F1].` }],
          ['done', { cited: ['F1'] }],
        ),
      ),
    )
  })
  await page.setViewportSize({ width: 1440, height: 900 })
  await ready(page)
  const fab = page.getByRole('button', { name: 'Ask', exact: true })
  await fab.click()
  await page.getByLabel('Ask about UIUC research').fill('computer vision')
  await page.keyboard.press('Enter')
  const log = page.getByRole('log', { name: 'Conversation' })
  await expect(log).toContainText(`${person.name} works on vision`)
  expect(sent).toMatchObject({ message: 'computer vision', history: [] })
  await expect(log.getByRole('listitem').filter({ hasText: person.name }).first()).toBeVisible()
  await log.getByRole('button', { name: new RegExp(`${person.name} \\(faculty\\)`) }).first().click()
  await expect(page.getByRole('dialog', { name: 'Assistant' })).toBeHidden()
  const drawer = page.getByRole('dialog', { name: 'Faculty profile' })
  await expect(drawer).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(drawer).toBeHidden()
  await expect(fab).toBeFocused()
})

test('a failed chat turn can be retried, and the earlier turns are sent as history', async ({ page }) => {
  let calls = 0
  const bodies: { message: string; history: { role: string; content: string }[] }[] = []
  await page.route('**/api/chat', (route) => {
    calls += 1
    bodies.push(route.request().postDataJSON())
    if (calls === 2) return route.abort()
    if (calls === 4) return route.fulfill(reply(sse(['error', { message: 'The language model is not reachable right now.' }])))
    return route.fulfill(
      reply(
        sse(
          ['sources', { sources: [{ ref: 'P1', kind: 'paper', label: 'A paper', date: '2026-01-02', doi: null, paperId: 'W1' }] }],
          ['delta', { text: calls === 1 ? 'I found nothing about that.' : 'Here is one [P1].' }],
          ['done', { cited: calls === 1 ? [] : ['P1'] }],
        ),
      ),
    )
  })
  await ready(page)
  await page.getByRole('button', { name: 'Ask', exact: true }).click()
  const input = page.getByLabel('Ask about UIUC research')
  const log = page.getByRole('log')
  await input.fill('zzzqqqxxx')
  await page.keyboard.press('Enter')
  await expect(log).toContainText('I found nothing about that.')

  await input.fill('robotics')
  await page.keyboard.press('Enter')
  await expect(log.getByRole('button', { name: 'Try again' })).toBeVisible()
  await log.getByRole('button', { name: 'Try again' }).click()
  await expect(log).toContainText('Here is one')
  expect(bodies[2]).toMatchObject({ message: 'robotics', history: [{ role: 'user', content: 'zzzqqqxxx' }, { role: 'assistant', content: 'I found nothing about that.' }] })

  await input.fill('and then?')
  await page.keyboard.press('Enter')
  await expect(log.getByRole('button', { name: 'Try again' })).toBeVisible()
  await expect(log).toContainText('not reachable')
})

type ChatBody = { message: string; history: unknown[]; context?: { kind: string; id: number }; known: { kind: string; id: string }[] }

test('asking from a profile opens the chat about that person, and the profile can be dropped', async ({ page }) => {
  const bodies: ChatBody[] = []
  await page.route('**/api/chat', (route) => {
    bodies.push(route.request().postDataJSON())
    return route.fulfill(reply(sse(['delta', { text: 'Ok.' }], ['done', { cited: [] }])))
  })
  await page.setViewportSize({ width: 1440, height: 900 })
  await ready(page)
  await page.getByRole('button', { name: /linked papers/ }).first().click()
  const drawer = page.getByRole('dialog', { name: 'Faculty profile' })
  const name = (await drawer.getByRole('heading', { level: 3 }).textContent())!
  await drawer.getByRole('button', { name: 'Ask the assistant about this person' }).click()

  const chat = page.getByRole('dialog', { name: 'Assistant' })
  await expect(drawer).toBeHidden()
  await expect(chat).toBeVisible()
  await expect(page.getByLabel('Ask about UIUC research')).toBeFocused()
  await expect(chat.getByText(`Asking about ${name}`)).toBeVisible()
  await expect(chat.getByRole('button', { name: `What has ${name} published recently?` })).toBeVisible()

  await page.keyboard.type('and their topics?')
  await page.keyboard.press('Enter')
  await expect(page.getByRole('log')).toContainText('Ok.')
  expect(bodies[0]).toMatchObject({ message: 'and their topics?', context: { kind: 'faculty' }, known: [] })

  await chat.getByRole('button', { name: `Stop asking about ${name}` }).click()
  await page.getByLabel('Ask about UIUC research').fill('something else')
  await page.keyboard.press('Enter')
  await expect(page.getByRole('log').getByText('Ok.')).toHaveCount(2)
  expect(bodies[1]!.context).toBeUndefined()
})

test('records cited in an answer are sent as known on the next question', async ({ page }) => {
  const bodies: ChatBody[] = []
  await page.route('**/api/chat', (route) => {
    bodies.push(route.request().postDataJSON())
    return route.fulfill(
      reply(
        sse(
          [
            'sources',
            {
              sources: [
                { ref: 'F1', kind: 'faculty', label: 'Ada Lovelace', facultyId: 7 },
                { ref: 'P1', kind: 'paper', label: 'On engines', date: '2026-01-02', doi: null, paperId: 'W9' },
                { ref: 'P2', kind: 'paper', label: 'Not cited', date: '2026-01-03', doi: null, paperId: 'W10' },
              ],
            },
          ],
          ['delta', { text: 'Ada [F1] wrote [P1].' }],
          ['done', { cited: ['F1', 'P1'] }],
        ),
      ),
    )
  })
  await ready(page)
  await page.getByRole('button', { name: 'Ask', exact: true }).click()
  const input = page.getByLabel('Ask about UIUC research')
  for (const q of ['first', 'second']) {
    await input.fill(q)
    await page.keyboard.press('Enter')
    await expect(page.getByRole('log').getByText('wrote', { exact: false })).toHaveCount(q === 'first' ? 1 : 2)
  }
  expect(bodies[0]!.known).toEqual([])
  expect(bodies[1]!.known).toEqual([
    { kind: 'faculty', id: '7' },
    { kind: 'paper', id: 'W9' },
  ])
})

test('the conversation survives a reload, and New chat clears it for good', async ({ page }) => {
  await page.route('**/api/chat', (route) =>
    route.fulfill(reply(sse(['delta', { text: 'Remembered answer.' }], ['done', { cited: [] }]))),
  )
  await page.setViewportSize({ width: 1440, height: 900 })
  await ready(page)
  await page.getByRole('button', { name: 'Ask', exact: true }).click()
  await page.getByLabel('Ask about UIUC research').fill('remember me')
  await page.keyboard.press('Enter')
  await expect(page.getByRole('log')).toContainText('Remembered answer.')

  await page.reload()
  await page.getByRole('button', { name: 'Ask', exact: true }).click()
  const log = page.getByRole('log')
  await expect(log).toContainText('remember me')
  await expect(log).toContainText('Remembered answer.')

  await page.getByRole('button', { name: 'New chat' }).click()
  await expect(log).not.toContainText('Remembered answer.')
  await expect(page.getByRole('button', { name: 'New chat' })).toBeHidden()
  await page.reload()
  await page.getByRole('button', { name: 'Ask', exact: true }).click()
  await expect(page.getByRole('log')).not.toContainText('remember me')
})

test('a reloaded session sends the open profile and the cited records again', async ({ page }) => {
  const bodies: ChatBody[] = []
  await page.route('**/api/chat', (route) => {
    bodies.push(route.request().postDataJSON())
    return route.fulfill(
      reply(
        sse(
          [
            'sources',
            {
              sources: [
                { ref: 'F1', kind: 'faculty', label: 'Ada Lovelace', facultyId: 7 },
                { ref: 'P1', kind: 'paper', label: 'On engines', date: '2026-01-02', doi: null, paperId: 'W9' },
              ],
            },
          ],
          ['delta', { text: 'Ada [F1] wrote [P1].' }],
          ['done', { cited: ['F1', 'P1'] }],
        ),
      ),
    )
  })
  await page.setViewportSize({ width: 1440, height: 900 })
  await ready(page)
  await page.getByRole('button', { name: /linked papers/ }).first().click()
  const drawer = page.getByRole('dialog', { name: 'Faculty profile' })
  const name = (await drawer.getByRole('heading', { level: 3 }).textContent())!
  await drawer.getByRole('button', { name: 'Ask the assistant about this person' }).click()
  await page.getByLabel('Ask about UIUC research').fill('their latest paper')
  await page.keyboard.press('Enter')
  const log = page.getByRole('log')
  await expect(log.getByRole('button', { name: 'Ada Lovelace (faculty)' }).first()).toBeVisible()
  const facultyId = bodies[0]!.context!.id

  await page.reload()
  await page.getByRole('button', { name: 'Ask', exact: true }).click()
  const chat = page.getByRole('dialog', { name: 'Assistant' })
  await expect(chat.getByText(`Asking about ${name}`)).toBeVisible()
  await expect(log).toContainText('their latest paper')
  await expect(log.getByRole('button', { name: 'Ada Lovelace (faculty)' }).first()).toBeVisible()
  await expect(log.getByText('On engines')).toBeVisible()

  await page.getByLabel('Ask about UIUC research').fill('and another')
  await page.keyboard.press('Enter')
  await expect(log.getByText('wrote', { exact: false })).toHaveCount(2)
  expect(bodies[1]).toMatchObject({
    message: 'and another',
    context: { kind: 'faculty', id: facultyId },
    history: [
      { role: 'user', content: 'their latest paper' },
      { role: 'assistant', content: 'Ada wrote.' },
    ],
    known: [
      { kind: 'faculty', id: '7' },
      { kind: 'paper', id: 'W9' },
    ],
  })

  await chat.getByRole('button', { name: 'New chat' }).click()
  await expect(chat.getByText(`Asking about ${name}`)).toBeHidden()
  await page.reload()
  await page.getByRole('button', { name: 'Ask', exact: true }).click()
  await expect(page.getByRole('log')).not.toContainText('their latest paper')
  await expect(page.getByText(`Asking about ${name}`)).toHaveCount(0)
})

test('a stopped question is left out of the saved session', async ({ page }) => {
  let release: () => void = () => {}
  const hung = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.route('**/api/chat', async (route) => {
    await hung
    await route.abort().catch(() => {})
  })
  try {
    await ready(page)
    await page.getByRole('button', { name: 'Ask', exact: true }).click()
    await page.getByLabel('Ask about UIUC research').fill('unfinished question')
    await page.keyboard.press('Enter')
    await page.getByRole('button', { name: 'Stop', exact: true }).click()
    await expect(page.getByRole('button', { name: 'Stop', exact: true })).toBeHidden()
    await page.reload()
    await page.getByRole('button', { name: 'Ask', exact: true }).click()
    await expect(page.getByRole('log')).toContainText('Try a question')
    await expect(page.getByRole('log')).not.toContainText('unfinished question')
  } finally {
    release()
  }
})

test('a sample question is sent as written', async ({ page }) => {
  let sent: ChatBody | undefined
  await page.route('**/api/chat', (route) => {
    sent = route.request().postDataJSON()
    return route.fulfill(reply(sse(['delta', { text: 'Ok.' }], ['done', { cited: [] }])))
  })
  await ready(page)
  await page.getByRole('button', { name: 'Ask', exact: true }).click()
  const question = 'What are the most recent UIUC papers on AI in war conflict?'
  await page.getByRole('button', { name: question }).click()
  await expect(page.getByRole('log')).toContainText('Ok.')
  expect(sent).toMatchObject({ message: question, history: [], known: [] })
  expect(sent!.context).toBeUndefined()
})

test('chat on a tablet is a full-screen modal', async ({ page }) => {
  await page.setViewportSize({ width: 768, height: 900 })
  await ready(page)
  await page.getByRole('button', { name: 'Ask', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Assistant' })
  await expect(dialog).toBeVisible()
  const box = await dialog.boundingBox()
  expect(box).toMatchObject({ x: 0, y: 0, width: 768, height: 900 })
  expect(await dialog.evaluate((el) => el.matches(':modal'))).toBe(true)
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
})

test('no serious accessibility violations with the chat or the faculty drawer open', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await ready(page)
  await page.getByRole('button', { name: 'Ask', exact: true }).click()
  await expect(page.getByRole('dialog', { name: 'Assistant' })).toBeVisible()
  const chat = await new AxeBuilder({ page }).analyze()
  const chatBad = chat.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
  expect(chatBad.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`)).toEqual([])
  await page.keyboard.press('Escape')

  await page.getByRole('button', { name: /linked papers/ }).first().click()
  const profile = page.getByRole('dialog', { name: 'Faculty profile' })
  await expect(profile.getByRole('button', { name: 'Ask the assistant about this person' })).toBeVisible()
  await profile.locator('.fade-in').evaluate((el) => Promise.all(el.getAnimations().map((animation) => animation.finished)))
  const drawer = await new AxeBuilder({ page }).analyze()
  const drawerBad = drawer.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
  expect(drawerBad.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`)).toEqual([])
})

test('a later question sends only the last eight messages', async ({ page }) => {
  const bodies: { message: string; history: { role: string; content: string }[] }[] = []
  await page.route('**/api/chat', (route) => {
    bodies.push(route.request().postDataJSON())
    return route.fulfill(reply(sse(['delta', { text: `a${bodies.length}` }], ['done', { cited: [] }])))
  })
  await ready(page)
  await page.getByRole('button', { name: 'Ask', exact: true }).click()
  const input = page.getByLabel('Ask about UIUC research')
  const log = page.getByRole('log')
  for (let n = 1; n <= 6; n++) {
    await input.fill(`q${n}`)
    await page.keyboard.press('Enter')
    await expect(log).toContainText(`a${n}`)
  }
  expect(bodies[5]!.message).toBe('q6')
  expect(bodies[5]!.history.map((turn) => turn.content)).toEqual(['q2', 'a2', 'q3', 'a3', 'q4', 'a4', 'q5', 'a5'])
})

test('stopping an answer keeps the question and shows no error', async ({ page }) => {
  let release: () => void = () => {}
  const hung = new Promise<void>((resolve) => {
    release = resolve
  })
  await page.route('**/api/chat', async (route) => {
    await hung
    await route.abort().catch(() => {})
  })
  try {
    await ready(page)
    await page.getByRole('button', { name: 'Ask', exact: true }).click()
    await page.getByLabel('Ask about UIUC research').fill('keep this question')
    await page.keyboard.press('Enter')
    const stop = page.getByRole('button', { name: 'Stop', exact: true })
    await expect(stop).toBeVisible()
    await stop.click()
    await expect(stop).toBeHidden()
    await expect(page.getByRole('log')).toContainText('keep this question')
    await expect(page.getByRole('button', { name: 'Try again' })).toHaveCount(0)
    await expect(page.getByText('Your question was not answered.')).toHaveCount(0)
  } finally {
    release()
  }
})

test('anchors are not hidden under the sticky header', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 700 })
  await ready(page)
  await page.getByRole('link', { name: 'Faculty', exact: true }).click()
  await page.waitForTimeout(800)
  const header = await page.locator('header').first().boundingBox()
  const title = await page.locator('#faculty-title').boundingBox()
  expect(title!.y).toBeGreaterThanOrEqual(header!.y + header!.height - 1)
})

test('no horizontal overflow at 375px', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 800 })
  await ready(page)
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(overflow).toBeLessThanOrEqual(0)
})
