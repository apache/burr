"use client";

import { useState, useEffect } from "react";
import { useTheme } from "next-themes";
import { NAV_LINKS, GITHUB_REPO, DISCORD_URL } from "@/lib/constants";
import { Menu, X, Sun, Moon, Github, MessageCircle } from "lucide-react";
import { BASE_PATH } from "@/lib/constants";

export default function Navbar() {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [stars, setStars] = useState<string | null>(null);
  const [scrolled, setScrolled] = useState(false);
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    fetch("https://api.github.com/repos/apache/burr")
      .then((r) => r.json())
      .then((d) => {
        if (d.stargazers_count) {
          setStars(
            d.stargazers_count >= 1000
              ? `${(d.stargazers_count / 1000).toFixed(1)}k`
              : String(d.stargazers_count)
          );
        }
      })
      .catch(() => {});

    const onScroll = () => setScrolled(window.scrollY > 10);
    window.addEventListener("scroll", onScroll);
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <nav
      className={`sticky top-0 z-50 transition-all duration-200 ${
        scrolled
          ? "bg-[var(--bg)]/80 backdrop-blur-lg border-b border-[var(--card-border)]"
          : "bg-transparent"
      }`}
    >
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="flex h-16 items-center justify-between">
          {/* Logo */}
          <a href="/" className="flex items-center gap-2.5">
            <img src={`${BASE_PATH}/burr_logo.svg`} alt="Burr" className="h-8 w-8" />
            <span className="text-lg font-bold">Apache Burr<sup className="text-[10px] font-normal text-[var(--muted)] ml-0.5">Incubating</sup></span>
          </a>

          {/* Desktop links */}
          <div className="hidden md:flex items-center gap-6">
            {NAV_LINKS.map((link) => (
              <a
                key={link.label}
                href={link.href}
                target={link.external ? "_blank" : undefined}
                rel={link.external ? "noopener noreferrer" : undefined}
                className="text-sm font-medium text-[var(--muted)] hover:text-[var(--text)] transition-colors"
              >
                {link.label}
              </a>
            ))}
          </div>

          {/* Right side */}
          <div className="hidden md:flex items-center gap-3">
            <a
              href={DISCORD_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm text-[var(--muted)] hover:text-[var(--text)] hover:bg-[var(--card-border)]/50 transition-colors"
            >
              <MessageCircle className="h-4 w-4" />
              Discord
            </a>
            <a
              href={GITHUB_REPO}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm text-[var(--muted)] hover:text-[var(--text)] hover:bg-[var(--card-border)]/50 transition-colors"
            >
              <Github className="h-4 w-4" />
              {stars && <span>{stars}</span>}
            </a>
            {mounted && (
              <button
                onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
                className="rounded-lg p-2 text-[var(--muted)] hover:text-[var(--text)] hover:bg-[var(--card-border)]/50 transition-colors"
                aria-label="Toggle theme"
              >
                {theme === "dark" ? (
                  <Sun className="h-4 w-4" />
                ) : (
                  <Moon className="h-4 w-4" />
                )}
              </button>
            )}
          </div>

          {/* Mobile hamburger */}
          <button
            className="md:hidden rounded-lg p-2 text-[var(--muted)] hover:text-[var(--text)]"
            onClick={() => setMobileOpen(!mobileOpen)}
            aria-label="Toggle menu"
          >
            {mobileOpen ? (
              <X className="h-5 w-5" />
            ) : (
              <Menu className="h-5 w-5" />
            )}
          </button>
        </div>

        {/* Mobile menu */}
        {mobileOpen && (
          <div className="md:hidden border-t border-[var(--card-border)] py-4 space-y-3">
            {NAV_LINKS.map((link) => (
              <a
                key={link.label}
                href={link.href}
                target={link.external ? "_blank" : undefined}
                className="block text-sm font-medium text-[var(--muted)] hover:text-[var(--text)]"
                onClick={() => setMobileOpen(false)}
              >
                {link.label}
              </a>
            ))}
            <div className="flex items-center gap-3 pt-2">
              <a
                href={GITHUB_REPO}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1.5 text-sm text-[var(--muted)]"
              >
                <Github className="h-4 w-4" /> GitHub {stars && `(${stars})`}
              </a>
              {mounted && (
                <button
                  onClick={() =>
                    setTheme(theme === "dark" ? "light" : "dark")
                  }
                  className="rounded-lg p-2 text-[var(--muted)]"
                >
                  {theme === "dark" ? (
                    <Sun className="h-4 w-4" />
                  ) : (
                    <Moon className="h-4 w-4" />
                  )}
                </button>
              )}
            </div>
          </div>
        )}
      </div>
    </nav>
  );
}
