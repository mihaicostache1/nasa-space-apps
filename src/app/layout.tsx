import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Lunar Landing Site Navigator',
  description:
    'A NASA Space Apps project for comparing lunar landing sites and dates.',
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
