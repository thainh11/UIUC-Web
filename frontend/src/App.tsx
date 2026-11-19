import { ChatCircle } from '@phosphor-icons/react'
import { lazy, Suspense, useCallback, useRef, useState, type ReactNode } from 'react'
import { ChatPanel } from './components/ChatPanel'
import { FacultyDrawer } from './components/FacultyDrawer'
import { FacultySection } from './components/FacultySection'
import { Footer } from './components/Footer'
import { Header } from './components/Header'
import { Hero } from './components/Hero'
import { PapersSection } from './components/PapersSection'
import { Skeleton } from './components/states'
import { StatCards } from './components/StatCards'
import { TopicBars } from './components/TopicBars'
import { usePageState } from './hooks/usePageState'
import { loadChat, type PageContext } from './lib/chatStore'

// Recharts is most of the bundle and the chart sits below the fold: load it as its own chunk.
const PublicationsChart = lazy(() => import('./components/PublicationsChart').then((m) => ({ default: m.PublicationsChart })))

function Section({ id, title, intro, children }: { id: string; title: string; intro?: string; children: ReactNode }) {
  return (
    <section id={id} aria-labelledby={`${id}-title`} className="mt-14">
      <h2 id={`${id}-title`} className="m-0 text-3xl">
        {title}
      </h2>
      {intro && <p className="text-muted-fg mt-1 mb-6 max-w-[65ch]">{intro}</p>}
      {!intro && <div className="mb-6" />}
      {children}
    </section>
  )
}

export default function App() {
  const [state, update] = usePageState()
  const [chatOpen, setChatOpen] = useState(false)
  const [facultyId, setFacultyId] = useState<number | null>(null)
  const [chatContext, setChatContext] = useState<PageContext | null>(() => loadChat().context)
  const askButton = useRef<HTMLButtonElement>(null)
  const chatOpener = useRef<HTMLElement | null>(null)
  const drawerOpener = useRef<HTMLElement | null>(null)

  const openChat = useCallback((opener: HTMLElement) => {
    chatOpener.current = opener
    setChatOpen(true)
  }, [])
  const closeChat = useCallback(() => setChatOpen(false), [])
  const chatReturn = useCallback(() => chatOpener.current, [])
  const drawerReturn = useCallback(() => drawerOpener.current, [])

  // Only one overlay at a time: the drawer is modal, so the chat closes when a citation opens it.
  const openFacultyFrom = useCallback((id: number, opener: HTMLElement | null) => {
    drawerOpener.current = opener
    setChatOpen(false)
    setFacultyId(id)
  }, [])

  // The drawer is modal and restores focus when it closes: open the chat on the next frame so its input keeps focus.
  const askAboutFaculty = useCallback((id: number, name: string) => {
    chatOpener.current = askButton.current
    setChatContext({ kind: 'faculty', id, name })
    setFacultyId(null)
    requestAnimationFrame(() => setChatOpen(true))
  }, [])

  const selectField = useCallback(
    (field: string | null) => {
      update({ field, page: 1 })
      if (field) {
        requestAnimationFrame(() => document.getElementById('papers-summary')?.focus())
      }
    },
    [update],
  )

  return (
    <>
      <a
        href="#main"
        className="bg-primary text-primary-fg sr-only z-50 rounded-md px-4 py-2 font-bold focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
      >
        Skip to content
      </a>
      <Header onOpenChat={openChat} />
      <Hero />
      <main id="main" className="mx-auto max-w-[70rem] px-4 pt-8 min-[1440px]:px-0">
        <StatCards />

        <Section id="output" title="Publications per month" intro="Papers by publication date, last two years.">
          <Suspense fallback={<Skeleton className="h-[17rem] w-full" />}>
            <PublicationsChart />
          </Suspense>
        </Section>

        <Section
          id="topics"
          title="Focus areas"
          intro="Papers by research field, using each paper’s primary topic. Select a field to filter the papers below."
        >
          <TopicBars selected={state.field} onSelect={selectField} />
        </Section>

        <Section id="papers" title="Papers">
          <PapersSection state={state} update={update} onOpenFaculty={openFacultyFrom} />
        </Section>

        <Section id="faculty" title="Faculty" intro="Directory entries, most linked papers first.">
          <FacultySection state={state} update={update} onOpenFaculty={openFacultyFrom} />
        </Section>
      </main>
      <Footer />

      <button
        ref={askButton}
        type="button"
        aria-haspopup="dialog"
        aria-expanded={chatOpen}
        onClick={(e) => openChat(e.currentTarget)}
        className="btn btn-primary fixed right-4 bottom-4 z-40 h-14 rounded-full px-5 shadow-lg lg:right-6 lg:bottom-6"
      >
        <ChatCircle size={24} weight="fill" aria-hidden="true" />
        Ask
      </button>

      <ChatPanel
        open={chatOpen}
        onClose={closeChat}
        context={chatContext}
        onContextChange={setChatContext}
        onOpenFaculty={(id) => openFacultyFrom(id, chatOpener.current)}
        getReturnFocus={chatReturn}
      />
      <FacultyDrawer facultyId={facultyId} onClose={() => setFacultyId(null)} onAsk={askAboutFaculty} getReturnFocus={drawerReturn} />
    </>
  )
}
