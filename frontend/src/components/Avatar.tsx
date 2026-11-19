import { useState } from 'react'
import { initials, realPhotoUrl } from '../lib/format'

type Props = { name: string; url: string | null; className?: string }

/**
 * Faculty photo, or letter initials when there is none, it is the Experts "no portrait" placeholder,
 * or the third-party image fails to load. Decorative: the name is always rendered next to it.
 */
export function Avatar({ name, url, className = 'size-14 text-lg' }: Props) {
  const [failed, setFailed] = useState(false)
  const src = realPhotoUrl(url)

  if (!src || failed) {
    return (
      <span
        aria-hidden="true"
        className={`text-primary inline-flex shrink-0 items-center justify-center rounded-full bg-[#dfe6f1] font-bold ${className}`}
      >
        {initials(name)}
      </span>
    )
  }
  return (
    <img
      src={src}
      alt=""
      width={112}
      height={112}
      loading="lazy"
      referrerPolicy="no-referrer"
      onError={() => setFailed(true)}
      className={`shrink-0 rounded-full bg-[#dfe6f1] object-cover ${className}`}
    />
  )
}
