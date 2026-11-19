import { useCallback, useEffect, useState } from 'react'
import { parseState, serializeState, type PageState } from '../lib/urlState'

/** Page filters live in the query string (replaceState, no router) so reload and shared links keep them. */
export function usePageState() {
  const [state, setState] = useState<PageState>(() => parseState(window.location.search))

  useEffect(() => {
    const url = `${window.location.pathname}${serializeState(state)}${window.location.hash}`
    window.history.replaceState(null, '', url)
  }, [state])

  const update = useCallback((patch: Partial<PageState>) => setState((s) => ({ ...s, ...patch })), [])
  return [state, update] as const
}
