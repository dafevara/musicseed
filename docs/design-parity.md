# MusicSeed web UI parity checklist

The product UI and the public website have different jobs, but they should feel like
the same MusicSeed experience. Shared tokens live in `web/src/app/tokens.css` and
`../website/assets/tokens.css`; changes to either vocabulary should be reflected in
both files.

## Automated checks

From the `musicseed` repository root:

```sh
./scripts/check_design_parity.sh ../website
(cd web && npx tsc --noEmit && npm run build)
```

The parity script checks that both surfaces expose the shared token vocabulary and
that each surface still has the expected shell, hierarchy, control, surface, and
keyboard-focus patterns.

## Review checklist

- [ ] Canvas, surface, text, accent, semantic-status, border, focus, type, radius,
      and motion tokens remain aligned across both token files.
- [ ] Brand mark, wordmark, accent gradient, and active/focus states are recognizable
      in both surfaces.
- [ ] Buttons have the same visual language, minimum hit area, disabled treatment,
      and keyboard focus treatment; marketing CTAs may remain more prominent.
- [ ] Panels, cards, code blocks, and popovers use the shared surface and radius
      hierarchy without making the product feel like a marketing page.
- [ ] Product pages expose a clear eyebrow, title, and purpose statement before the
      task-specific controls.
- [ ] Website sections retain their marketing hierarchy while using the same spacing,
      contrast, link, and focus conventions.
- [ ] Check desktop and narrow layouts, hover/focus/disabled states, long labels,
      empty states, errors, and first-run setup flows.
- [ ] Confirm no new hard-coded color, radius, or transition value bypasses a shared
      token without a documented reason.
