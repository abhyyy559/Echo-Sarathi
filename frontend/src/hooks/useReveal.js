import { useEffect, useRef } from 'react';

/**
 * Scroll-reveal: returns a ref for a container element. Every descendant
 * carrying `[data-reveal]` gets the `revealed` class the first time it
 * enters the viewport (one-way). Falls back to instantly-visible when
 * IntersectionObserver is unavailable.
 */
export default function useReveal() {
  const ref = useRef(null);

  useEffect(() => {
    const root = ref.current;
    if (!root) return undefined;
    const targets = Array.from(root.querySelectorAll('[data-reveal]'));
    if (targets.length === 0 || !('IntersectionObserver' in window)) {
      targets.forEach((el) => el.classList.add('revealed'));
      return undefined;
    }
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add('revealed');
            io.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.15 },
    );
    targets.forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, []);

  return ref;
}
