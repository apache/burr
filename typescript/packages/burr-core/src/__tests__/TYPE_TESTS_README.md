# Compile-Time Type Safety Tests

This directory contains compile-time type tests that verify TypeScript correctly catches type errors at definition time.

## Setup

Install `tsd` as a dev dependency:

```bash
npm install --save-dev tsd
```

## Running Tests

```bash
npm run test:types
```

This will:
1. Build the project (`npm run build`)
2. Copy `index.test-d.ts` to `dist/`
3. Run `tsd` which validates that:
   - `expectError()` calls actually produce TypeScript errors
   - `expectType<T>()` calls match the expected type
   - `expectAssignable<T>()` calls are valid

## Test File

- `index.test-d.ts` - Type tests for Actions and State
  - Write restrictions (can't write to non-writable fields)
  - Result + Run consistency (run required when result specified)
  - Run return type matching result schema
  - Covariance (update can return extra fields)
  - Multi-field operations (increment, append with multiple fields)

**Note:** Some type constraints (like excess property checking and NumberKeys) are primarily enforced at runtime by Zod, as TypeScript's structural typing makes compile-time enforcement complex in all scenarios.

## Why `tsd`?

Unlike runtime tests, these tests verify the TypeScript compiler's behavior:
- Ensures type errors are caught **before** code runs
- Documents expected type behavior
- Prevents regressions in type safety
- Validates complex generic types

## Example

```typescript
// ✅ This should compile
const state = createState(z.object({ count: z.number() }), { count: 0 });
state.increment({ count: 1 });

// ❌ This should NOT compile (count is not writable)
const restrictedState = State.forAction(
  z.object({ count: z.number() }),  // reads
  z.object({ result: z.number() }), // writes
  { count: 0 }
);
expectError(restrictedState.increment({ count: 1 }));  // Error caught by tsd!
```

## Writing New Tests

1. Edit `index.test-d.ts` in this directory
2. Use `expectError()` for code that should NOT compile
3. Use `expectAssignable()` or `expectType()` for code that should compile
4. Run `npm run test:types` to validate

See https://github.com/SamVerschueren/tsd for full documentation.

## Implementation Note

The test file lives in `src/__tests__/` and imports from `./index` (which resolves to `dist/index.d.ts`). During test runs, it's copied to `dist/` where tsd expects it. This keeps test files organized with other tests while working with tsd's conventions.

