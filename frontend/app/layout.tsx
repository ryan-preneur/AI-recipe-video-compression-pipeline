import './globals.css';
export const metadata = {title:'Recipe Reel Studio',description:'Turn recipes into short, useful videos in your language'};
export default function RootLayout({children}:{children:React.ReactNode}){return <html lang="en"><body>{children}</body></html>}
