/**
 * Copyright (c) 2024-2025 Elijah ben Izzy
 * SPDX-License-Identifier: Apache-2.0
 * 
 * Compile-time type safety tests for generic type utilities using tsd.
 * Run with: npm run test:types
 * 
 * These tests verify that generic type utilities work correctly at compile time.
 * tsd will verify that expectError() directives actually produce errors.
 */

import { z } from 'zod';
import { expectError, expectAssignable } from 'tsd';
import {
  UseIfNotSet,
  EnsureRecordSchema,
  ValidateSchemaExtends,
  ConditionalValidate
} from '../type-utils';

// ============================================================================
// UseIfNotSet Tests
// ============================================================================

// ✅ If Existing is ZodNever, use New
{
  type NewSchema = z.ZodObject<{ a: z.ZodNumber }>;
  type Result = UseIfNotSet<z.ZodNever, NewSchema>;
  expectAssignable<NewSchema>({} as Result);
}

// ✅ If Existing is set, keep Existing (ignore New)
{
  type Existing = z.ZodObject<{ count: z.ZodNumber }>;
  type New = z.ZodObject<{ name: z.ZodString }>;
  type Result = UseIfNotSet<Existing, New>;
  expectAssignable<Existing>({} as Result);
  // Should NOT be New
  expectError(expectAssignable<New>({} as Result));
}

// ✅ Works with different schema types
{
  type ArraySchema = z.ZodArray<z.ZodString>;
  type Result = UseIfNotSet<z.ZodNever, ArraySchema>;
  expectAssignable<ArraySchema>({} as Result);
}

// ✅ Chaining works correctly
{
  type First = z.ZodObject<{ a: z.ZodNumber }>;
  type Second = z.ZodObject<{ b: z.ZodString }>;
  type Third = z.ZodObject<{ c: z.ZodBoolean }>;
  
  type Step1 = UseIfNotSet<z.ZodNever, First>; // => First
  type Step2 = UseIfNotSet<Step1, Second>; // => First (keeps existing)
  type Step3 = UseIfNotSet<Step2, Third>; // => First (keeps existing)
  
  expectAssignable<First>({} as Step3);
}

// ============================================================================
// EnsureRecordSchema Tests
// ============================================================================

// ✅ ZodNever converts to Record schema
{
  type Result = EnsureRecordSchema<z.ZodNever>;
  expectAssignable<z.ZodType<Record<string, any>>>({} as Result);
}

// ✅ Valid Record schema passes through unchanged
{
  const schema = z.object({ a: z.number(), b: z.string() });
  type Result = EnsureRecordSchema<typeof schema>;
  expectAssignable<typeof schema>({} as Result);
}

// ✅ Empty object schema passes through
{
  const emptySchema = z.object({});
  type Result = EnsureRecordSchema<typeof emptySchema>;
  expectAssignable<typeof emptySchema>({} as Result);
}

// ✅ Nested object schema passes through
{
  const nestedSchema = z.object({
    user: z.object({
      name: z.string(),
      age: z.number()
    })
  });
  type Result = EnsureRecordSchema<typeof nestedSchema>;
  expectAssignable<typeof nestedSchema>({} as Result);
}

// ✅ Array schema converts to Record (not a Record, so gets converted)
{
  const arraySchema = z.array(z.string());
  type Result = EnsureRecordSchema<typeof arraySchema>;
  expectAssignable<z.ZodType<Record<string, any>>>({} as Result);
}

// ============================================================================
// ValidateSchemaExtends Tests
// ============================================================================

// ✅ Superset extends subset - returns TNew
{
  type Superset = z.ZodObject<{ a: z.ZodNumber; b: z.ZodString }>;
  type Subset = z.ZodObject<{ a: z.ZodNumber }>;
  type Result = ValidateSchemaExtends<Superset, Subset>;
  expectAssignable<Superset>({} as Result);
}

// ✅ Exact match - returns TNew
{
  type Exact = z.ZodObject<{ a: z.ZodNumber; b: z.ZodString }>;
  type Result = ValidateSchemaExtends<Exact, Exact>;
  expectAssignable<Exact>({} as Result);
}

// ✅ Subset does not extend superset - returns error type
{
  type Subset = z.ZodObject<{ a: z.ZodNumber }>;
  type Superset = z.ZodObject<{ a: z.ZodNumber; b: z.ZodString }>;
  type Result = ValidateSchemaExtends<Subset, Superset>;
  expectAssignable<{ '❌ Schema constraint violation': z.infer<Superset> }>({} as Result);
}

// ✅ Custom error message works
{
  type Subset = z.ZodObject<{ a: z.ZodNumber }>;
  type Superset = z.ZodObject<{ a: z.ZodNumber; b: z.ZodString }>;
  type Result = ValidateSchemaExtends<Subset, Superset, 'Custom error message'>;
  expectAssignable<{ 'Custom error message': z.infer<Superset> }>({} as Result);
}

// ✅ Works with optional fields (superset has optional, subset doesn't)
{
  type Superset = z.ZodObject<{ 
    a: z.ZodNumber;
    b: z.ZodOptional<z.ZodString>;
  }>;
  type Subset = z.ZodObject<{ a: z.ZodNumber }>;
  type Result = ValidateSchemaExtends<Superset, Subset>;
  expectAssignable<Superset>({} as Result);
}

// ✅ Fails when subset has required field that superset doesn't
{
  type Superset = z.ZodObject<{ a: z.ZodNumber }>;
  type Subset = z.ZodObject<{ a: z.ZodNumber; b: z.ZodString }>;
  type Result = ValidateSchemaExtends<Superset, Subset>;
  expectAssignable<{ '❌ Schema constraint violation': z.infer<Subset> }>({} as Result);
}

// ============================================================================
// ConditionalValidate Tests
// ============================================================================

// ✅ If TExisting is ZodNever, allow TNew (no validation)
{
  type New = z.ZodObject<{ a: z.ZodNumber }>;
  type Result = ConditionalValidate<New, z.ZodNever>;
  expectAssignable<New>({} as Result);
}

// ✅ If TExisting is set and compatible, allow TNew
{
  type New = z.ZodObject<{ a: z.ZodNumber; b: z.ZodString }>;
  type Existing = z.ZodObject<{ a: z.ZodNumber }>;
  type Result = ConditionalValidate<New, Existing>;
  expectAssignable<New>({} as Result);
}

// ✅ If TExisting is set and incompatible, return error type
{
  type New = z.ZodObject<{ a: z.ZodNumber }>;
  type Existing = z.ZodObject<{ a: z.ZodNumber; b: z.ZodString }>;
  type Result = ConditionalValidate<New, Existing>;
  expectAssignable<{ '❌ Schema constraint violation': z.infer<Existing> }>({} as Result);
}

// ✅ Custom error message works
{
  type New = z.ZodObject<{ a: z.ZodNumber }>;
  type Existing = z.ZodObject<{ a: z.ZodNumber; b: z.ZodString }>;
  type Result = ConditionalValidate<New, Existing, 'Custom validation error'>;
  expectAssignable<{ 'Custom validation error': z.infer<Existing> }>({} as Result);
}

// ✅ Works with exact match
{
  type Exact = z.ZodObject<{ a: z.ZodNumber; b: z.ZodString }>;
  type Result = ConditionalValidate<Exact, Exact>;
  expectAssignable<Exact>({} as Result);
}

// ✅ Empty schema validation
{
  type New = z.ZodObject<{ a: z.ZodNumber }>;
  type Empty = z.ZodObject<{}>;
  type Result = ConditionalValidate<New, Empty>;
  expectAssignable<New>({} as Result);
}

// ============================================================================
// Integration Tests: Combining Utilities
// ============================================================================

// ✅ UseIfNotSet + EnsureRecordSchema
{
  type Schema = z.ZodObject<{ count: z.ZodNumber }>;
  type Selected = UseIfNotSet<z.ZodNever, Schema>;
  type Ensured = EnsureRecordSchema<Selected>;
  expectAssignable<Schema>({} as Ensured);
}

// ✅ ConditionalValidate + UseIfNotSet pattern
{
  type New = z.ZodObject<{ a: z.ZodNumber; b: z.ZodString }>;
  type Existing = z.ZodObject<{ a: z.ZodNumber }>;
  
  // First validate
  type Validated = ConditionalValidate<New, Existing>;
  // Then select (if validated is not error type)
  type Selected = UseIfNotSet<z.ZodNever, Validated extends z.ZodType ? Validated : never>;
  expectAssignable<New>({} as Selected);
}

// ✅ Real-world builder pattern simulation
{
  // Simulate: builder.withGraph() then builder.withState()
  type GraphSchema = z.ZodObject<{ count: z.ZodNumber }>;
  type StateSchema = z.ZodObject<{ count: z.ZodNumber; name: z.ZodString }>;
  
  // Step 1: Set graph (no existing app schema)
  type AfterGraph = UseIfNotSet<z.ZodNever, GraphSchema>; // => GraphSchema
  
  // Step 2: Set state (graph schema exists, validate compatibility)
  type ValidatedState = ConditionalValidate<StateSchema, GraphSchema>;
  type AfterState = UseIfNotSet<AfterGraph, ValidatedState extends z.ZodType ? ValidatedState : never>;
  
  // Final state should be StateSchema (superset of GraphSchema)
  expectAssignable<StateSchema>({} as AfterState);
}

