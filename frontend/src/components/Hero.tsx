import { MapPin } from '@phosphor-icons/react'
import campus from '../assets/campus-main-quad.webp'

// Approximate centre of the Main Quad.
const MAP_URL = 'https://www.openstreetmap.org/?mlat=40.1070&mlon=-88.2272#map=14/40.1070/-88.2272'

export function Hero() {
  return (
    <section id="overview" className="on-primary relative isolate overflow-hidden text-white">
      <img
        src={campus}
        alt=""
        width={1920}
        height={1440}
        fetchPriority="high"
        className="absolute inset-0 -z-20 size-full object-cover"
      />
      <div aria-hidden="true" className="from-primary/95 via-primary/90 to-primary/75 absolute inset-0 -z-10 bg-gradient-to-r" />
      <div className="mx-auto max-w-[70rem] px-4 py-16 md:py-24 min-[1440px]:px-0">
        <p className="m-0 text-sm font-bold tracking-widest uppercase">University of Illinois Urbana-Champaign</p>
        <h1 className="m-0 mt-3 max-w-[18ch] text-5xl leading-tight text-white md:text-6xl">Research at Illinois</h1>
        <p className="mt-4 mb-0 max-w-[40ch] text-xl">Research output, last two years.</p>
        <p className="mt-6 mb-0 flex items-center gap-2">
          <MapPin size={20} weight="fill" aria-hidden="true" className="text-accent" />
          <a href={MAP_URL} target="_blank" rel="noopener noreferrer" className="text-white underline underline-offset-4">
            Urbana–Champaign, Illinois
            <span className="sr-only"> (opens map in new tab)</span>
          </a>
        </p>
        <div aria-hidden="true" className="bg-accent mt-8 h-1 w-24" />
      </div>
    </section>
  )
}
