import { useEffect, useState } from 'react'

const KEY = 'annotagent.ui_version'

export type UiVersion = 'v1' | 'v2'

/** Read the current UI version from localStorage. SSR-safe. */
export function getUiVersion(): UiVersion {
  try {
    const raw = localStorage.getItem(KEY)
    return raw === 'v1' ? 'v1' : 'v2'
  } catch {
    return 'v2'
  }
}

/** Hook: returns [version, setVersion]. Setting reloads the page so the
 * route table picks up the new component variants without further plumbing. */
export function useUiVersion(): [UiVersion, (next: UiVersion) => void] {
  const [v, setV] = useState<UiVersion>(getUiVersion)
  useEffect(() => {
    try { localStorage.setItem(KEY, v) } catch { /* ignore */ }
  }, [v])
  const set = (next: UiVersion) => {
    try { localStorage.setItem(KEY, next) } catch { /* ignore */ }
    setV(next)
    // Full reload — App.tsx and AppLayout pick versions on mount.
    window.location.reload()
  }
  return [v, set]
}
