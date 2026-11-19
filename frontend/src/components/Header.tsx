import { ChatCircle } from '@phosphor-icons/react'

const LINKS = [
  ['Overview', '#overview'],
  ['Output', '#output'],
  ['Topics', '#topics'],
  ['Papers', '#papers'],
  ['Faculty', '#faculty'],
] as const

export function Header({ onOpenChat }: { onOpenChat: (opener: HTMLElement) => void }) {
  return (
    <header className="border-border sticky top-0 z-30 border-b bg-white/95 backdrop-blur">
      <div className="mx-auto flex max-w-[70rem] flex-wrap items-center justify-between px-4 min-[1440px]:px-0 md:h-16 md:flex-nowrap md:gap-8">
        <a href="#overview" className="text-primary flex h-14 items-center gap-2 font-serif text-xl font-medium no-underline">
          <span aria-hidden="true" className="bg-primary inline-flex size-7 items-center justify-center rounded-md text-sm font-bold text-accent">
            I
          </span>
          UIUC Research
        </a>
        <button
          type="button"
          className="btn btn-primary md:order-3"
          onClick={(e) => onOpenChat(e.currentTarget)}
        >
          <ChatCircle size={20} aria-hidden="true" />
          Ask the assistant
        </button>
        <nav
          aria-label="Sections"
          className="-mx-4 flex h-12 w-[calc(100%+2rem)] items-center gap-1 overflow-x-auto px-4 md:order-2 md:mx-0 md:h-auto md:w-auto md:flex-1 md:overflow-visible md:px-0"
        >
          {LINKS.map(([label, href]) => (
            <a
              key={href}
              href={href}
              className="text-primary hover:bg-surface inline-flex min-h-11 shrink-0 items-center rounded-md px-3 font-bold no-underline"
            >
              {label}
            </a>
          ))}
        </nav>
      </div>
    </header>
  )
}
