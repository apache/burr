/**
 * Licensed to the Apache Software Foundation (ASF) under one
 * or more contributor license agreements.  See the NOTICE file
 * distributed with this work for additional information
 * regarding copyright ownership.  The ASF licenses this file
 * to you under the Apache License, Version 2.0 (the
 * "License"); you may not use this file except in compliance
 * with the License.  You may obtain a copy of the License at
 *
 *   http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing,
 * software distributed under the License is distributed on an
 * "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
 * KIND, either express or implied.  See the License for the
 * specific language governing permissions and limitations
 * under the License.
 */

/**
 * Runtime utilities for working with Zod schemas.
 * 
 * This module provides runtime helpers for dynamic schema operations:
 * - Extending schemas with new fields
 * - Inferring Zod types from runtime values
 * - Synchronizing multiple schemas
 * 
 * @module schema-utils
 */

import { z } from 'zod';

/**
 * Extends a Zod object schema with new fields, only if they don't already exist.
 * 
 * This is useful for dynamically extending state schemas when new fields are added
 * via operations like `update()`, `append()`, etc.
 * 
 * Returns the same schema instance if no extension is needed (performance optimization).
 * 
 * @param schema - Base ZodObject to extend
 * @param updates - Object containing the new field values
 * @param inferType - Whether to infer Zod types from values (true) or use z.unknown() (false)
 * @returns Extended schema or original if no changes needed
 * 
 * @example
 * ```typescript
 * const baseSchema = z.object({ a: z.number() });
 * const data = { a: 1, b: 'hello' };
 * 
 * // Extend with z.unknown() for new fields
 * const extended = extendSchemaWithFields(baseSchema, data, false);
 * // Result: z.object({ a: z.number(), b: z.unknown() })
 * 
 * // Extend with inferred types
 * const inferred = extendSchemaWithFields(baseSchema, data, true);
 * // Result: z.object({ a: z.number(), b: z.string() })
 * ```
 */
export function extendSchemaWithFields<T extends Record<string, any>>(
  schema: z.ZodObject<any>,
  updates: T,
  inferType: boolean = false
): z.ZodObject<any> {
  const extension: Record<string, z.ZodTypeAny> = {};
  
  for (const key in updates) {
    // Only add fields that don't exist in the schema
    if (!(key in schema.shape)) {
      extension[key] = inferType 
        ? inferZodType(updates[key])
        : z.unknown();
    }
  }
  
  // Only extend if we have new fields (avoid unnecessary work)
  return Object.keys(extension).length > 0
    ? schema.extend(extension)
    : schema;
}

/**
 * Infers a Zod type from a runtime value.
 * 
 * This provides basic type inference for common JavaScript types.
 * For complex objects, it returns a permissive schema with `passthrough()`.
 * 
 * @param value - Runtime value to infer type from
 * @returns Zod schema matching the value's type
 * 
 * @example
 * ```typescript
 * inferZodType('hello')  // => z.string()
 * inferZodType(42)       // => z.number()
 * inferZodType(true)     // => z.boolean()
 * inferZodType([1, 2])   // => z.array(z.unknown())
 * inferZodType({ a: 1 }) // => z.object({}).passthrough()
 * ```
 */
export function inferZodType(value: any): z.ZodTypeAny {
  if (typeof value === 'string') return z.string();
  if (typeof value === 'number') return z.number();
  if (typeof value === 'boolean') return z.boolean();
  if (value === null) return z.null();
  if (value === undefined) return z.undefined();
  if (Array.isArray(value)) {
    // Try to infer array element type from first element
    if (value.length > 0) {
      return z.array(inferZodType(value[0]));
    }
    return z.array(z.unknown());
  }
  if (value && typeof value === 'object') {
    // For objects, use a permissive schema
    // Could be extended to recursively infer field types
    return z.object({}).passthrough();
  }
  return z.unknown();
}

/**
 * Extends both a main schema and a readable schema with the same fields.
 * 
 * This is used in State mutation methods to keep the main schema and readable
 * schema in sync. When you write a field, it should also become readable.
 * 
 * @param mainSchema - Primary state schema to extend
 * @param readableSchema - Readable fields schema to extend
 * @param updates - Object containing the new field values
 * @param inferType - Whether to infer types or use z.unknown()
 * @returns Object with both extended schemas
 * 
 * @example
 * ```typescript
 * const main = z.object({ a: z.number() });
 * const readable = z.object({ a: z.number() });
 * const updates = { b: 'hello' };
 * 
 * const { main: newMain, readable: newReadable } = extendBothSchemas(
 *   main,
 *   readable,
 *   updates
 * );
 * 
 * // Both schemas now include 'b' field
 * ```
 */
export function extendBothSchemas(
  mainSchema: z.ZodObject<any>,
  readableSchema: z.ZodObject<any>,
  updates: Record<string, any>,
  inferType: boolean = false
): { main: z.ZodObject<any>; readable: z.ZodObject<any> } {
  return {
    main: extendSchemaWithFields(mainSchema, updates, inferType),
    readable: extendSchemaWithFields(readableSchema, updates, inferType)
  };
}

/**
 * Checks if a Zod schema is a ZodObject.
 * 
 * This is a type guard that can be used to safely narrow schema types
 * before accessing `.shape` or calling `.extend()`.
 * 
 * @param schema - Zod schema to check
 * @returns True if schema is a ZodObject
 * 
 * @example
 * ```typescript
 * const schema: z.ZodType = getSchema();
 * 
 * if (isZodObject(schema)) {
 *   // TypeScript knows schema is z.ZodObject here
 *   const keys = Object.keys(schema.shape);
 * }
 * ```
 */
export function isZodObject(schema: z.ZodType<any>): schema is z.ZodObject<any> {
  return schema instanceof z.ZodObject;
}

/**
 * Safely extends a schema only if it's a ZodObject, otherwise returns original.
 * 
 * This is useful when you're not sure if a schema is extendable, and you want
 * to avoid runtime errors from calling `.extend()` on non-object schemas.
 * 
 * @param schema - Schema to extend (may or may not be ZodObject)
 * @param updates - Fields to add
 * @param inferType - Whether to infer types
 * @returns Extended schema or original
 * 
 * @example
 * ```typescript
 * const schema: z.ZodType = z.string(); // Not an object!
 * const result = safeExtendSchema(schema, { a: 1 });
 * // Returns original schema (can't extend z.string())
 * ```
 */
export function safeExtendSchema(
  schema: z.ZodType<any>,
  updates: Record<string, any>,
  inferType: boolean = false
): z.ZodType<any> {
  if (isZodObject(schema)) {
    return extendSchemaWithFields(schema, updates, inferType);
  }
  return schema;
}

