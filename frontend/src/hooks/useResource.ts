import { useCallback, useEffect, useState } from 'react'

type State<T> = { data: T | null; error: Error | null; loading: boolean }

/**
 * Loads data and cancels the in-flight request when `deps` change or the component unmounts, so a slow
 * response for an old query can never overwrite a newer one. Keeps the previous `data` while reloading.
 */
export function useResource<T>(load: (signal: AbortSignal) => Promise<T>, deps: readonly unknown[]) {
  const [state, setState] = useState<State<T>>({ data: null, error: null, loading: true })
  const [nonce, setNonce] = useState(0)

  useEffect(() => {
    const ctrl = new AbortController()
    setState((s) => ({ ...s, error: null, loading: true }))
    load(ctrl.signal).then(
      (data) => setState({ data, error: null, loading: false }),
      (error: unknown) => {
        if (ctrl.signal.aborted) return
        setState((s) => ({ ...s, error: error instanceof Error ? error : new Error(String(error)), loading: false }))
      },
    )
    return () => ctrl.abort()
    // eslint-disable-next-line react-hooks/exhaustive-deps -- `load` is a fresh closure each render; `deps` is the contract
  }, [...deps, nonce])

  const reload = useCallback(() => setNonce((n) => n + 1), [])
  return { ...state, reload }
}
