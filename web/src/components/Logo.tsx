/** ScribSalmon mark: the dark salmon tile. web/public/logo.png comes from assets/icon-salmon-dark-256.png (tools/make_dark_icon.py). */
export default function Logo({ className = 'size-9' }: { className?: string }) {
  return <img src="./logo.png" alt="ScribSalmon" className={className} draggable={false} />
}
