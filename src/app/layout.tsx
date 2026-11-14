import type { Metadata } from 'next';
import './globals.css';
import '@/features/mission/styles/experience.css';

export const metadata: Metadata = {
  title: 'LunarWindow — Every landing has a window',
  description:
    'Explore lunar reference sites, sunlight, Earth visibility, and the operational windows that shape a mission.',
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
