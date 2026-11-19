import { X } from '@phosphor-icons/react'
import { useEffect, useId, useRef, type ReactNode, type RefObject } from 'react'

type Props = {
  open: boolean
  onClose: () => void
  title: string
  /** true: native modal (focus trap, inert page, Esc). false: non-modal panel, page stays usable. */
  modal: boolean
  /** Placement and size classes for the dialog element. */
  className: string
  /** Where focus goes on close. Defaults to whatever had focus when the overlay opened. */
  getReturnFocus?: () => HTMLElement | null
  /** Element to focus on open instead of the first focusable one (the close button). */
  initialFocus?: RefObject<HTMLElement | null>
  children: ReactNode
}

/**
 * The one dialog primitive for the faculty drawer and the chat panel. Built on <dialog>, so the browser
 * handles the focus trap, `inert` background and Esc for the modal case; we add Esc for the non-modal
 * case and restore focus in both.
 */
export function Overlay({ open, onClose, title, modal, className, getReturnFocus, initialFocus, children }: Props) {
  const ref = useRef<HTMLDialogElement>(null)
  const opener = useRef<HTMLElement | null>(null)
  const shownModal = useRef<boolean | null>(null)
  const titleId = useId()

  useEffect(() => {
    const dialog = ref.current
    if (!dialog) return
    if (open) {
      if (dialog.open && shownModal.current !== modal) dialog.close() // viewport crossed the modal breakpoint
      if (!dialog.open) {
        opener.current ??= document.activeElement as HTMLElement | null
        if (modal) dialog.showModal()
        else dialog.show()
        shownModal.current = modal
        initialFocus?.current?.focus()
      }
    } else if (dialog.open) {
      dialog.close()
      shownModal.current = null
      const target = getReturnFocus?.() ?? opener.current
      opener.current = null
      if (target?.isConnected) target.focus()
    }
  }, [open, modal, getReturnFocus, initialFocus])

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onCancel={(e) => {
        e.preventDefault() // we own the state; closing is driven by `open`
        onClose()
      }}
      onKeyDown={(e) => {
        if (e.key === 'Escape' && !modal) onClose()
      }}
      className={`bg-bg border-border flex-col overflow-hidden p-0 shadow-2xl open:flex ${className}`}
    >
      <header className="border-border flex items-center justify-between gap-3 border-b px-4 py-3">
        <h2 id={titleId} className="m-0 text-xl">
          {title}
        </h2>
        <button type="button" className="btn size-11 p-0" onClick={onClose} aria-label={`Close ${title}`}>
          <X size={20} aria-hidden="true" />
        </button>
      </header>
      {children}
    </dialog>
  )
}
