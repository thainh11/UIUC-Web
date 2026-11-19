export function Footer() {
  return (
    <footer className="bg-primary on-primary mt-16 text-white">
      <div className="mx-auto max-w-[70rem] space-y-2 px-4 py-8 pb-24 text-sm min-[1440px]:px-0">
        <p className="m-0">
          Publications: <a href="https://openalex.org" className="text-white underline underline-offset-2">OpenAlex</a>{' '}
          (CC0), University of Illinois Urbana-Champaign works from the last two years. Faculty: directory provided with the
          assignment.
        </p>
        <p className="m-0">
          Campus photo: “Main Quad – UIUC”, Daderot,{' '}
          <a href="https://commons.wikimedia.org/wiki/File:Main_Quad_-_UIUC_-_DSC09116.JPG" className="text-white underline underline-offset-2">
            Wikimedia Commons
          </a>
          , public domain.
        </p>
      </div>
    </footer>
  )
}
