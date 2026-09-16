import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { Gate } from "@/components/gate";
import { TooltipProvider } from "@/components/ui/tooltip";
import { PwaRegister } from "@/components/pwa-register";
import { Toaster } from "@/components/ui/sonner";

const geistSans = Geist({
  variable: "--font-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Print FarmOS",
  description: "Production control for the print farm.",
  applicationName: "Print FarmOS",
  manifest: "/manifest.webmanifest",
  appleWebApp: { capable: true, title: "Print FarmOS", statusBarStyle: "black-translucent" },
};

export const viewport = {
  themeColor: "#d97706",
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={`dark ${geistSans.variable} ${geistMono.variable} h-full`}>
      <body className="min-h-full">
        <TooltipProvider>
          <Gate>{children}</Gate>
          <Toaster />
          <PwaRegister />
        </TooltipProvider>
      </body>
    </html>
  );
}
