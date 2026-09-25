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

// Serialization and deserialization utilities
//
// Handles JS types that don't survive JSON.stringify (Date, Map, Set, etc.)
// Uses a tagged-value convention: { __serde_type: "Date", value: "..." }

// ============================================================================
// Types
// ============================================================================

/** Serializes a value into a JSON-safe representation */
export type Serializer = (value: any) => any;

/** Deserializes a JSON-safe representation back into the original value */
export type Deserializer = (data: any) => any;

export interface SerdeOptions {
  customSerializers?: Map<string, Serializer>;
  customDeserializers?: Map<string, Deserializer>;
}

/** Tagged value for non-JSON types */
interface TaggedValue {
  __serde_type: string;
  value: any;
}

function isTaggedValue(v: any): v is TaggedValue {
  return v !== null && typeof v === 'object' && typeof v.__serde_type === 'string';
}

// ============================================================================
// Built-in Serializers
// ============================================================================

const BUILTIN_SERIALIZERS = new Map<string, (v: any) => TaggedValue>();
BUILTIN_SERIALIZERS.set('Date', (v) => ({ __serde_type: 'Date', value: (v as Date).toISOString() }));
BUILTIN_SERIALIZERS.set('Map', (v) => ({ __serde_type: 'Map', value: [...(v as Map<any, any>).entries()] }));
BUILTIN_SERIALIZERS.set('Set', (v) => ({ __serde_type: 'Set', value: [...(v as Set<any>)] }));
BUILTIN_SERIALIZERS.set('RegExp', (v) => ({ __serde_type: 'RegExp', value: { source: (v as RegExp).source, flags: (v as RegExp).flags } }));
BUILTIN_SERIALIZERS.set('BigInt', (v) => ({ __serde_type: 'BigInt', value: (v as bigint).toString() }));

const BUILTIN_DESERIALIZERS = new Map<string, Deserializer>([
  ['Date', (data) => new Date(data as string)],
  ['Map', (data) => new Map(data as [any, any][])],
  ['Set', (data) => new Set(data as any[])],
  ['RegExp', (data) => {
    const { source, flags } = data as { source: string; flags: string };
    return new RegExp(source, flags);
  }],
  ['BigInt', (data) => BigInt(data as string)],
]);

// ============================================================================
// Core Functions
// ============================================================================

/**
 * Recursively serialize a value, converting non-JSON types to tagged values.
 */
export function serializeValue(value: any, options?: SerdeOptions): any {
  // Primitives pass through
  if (value === null || value === undefined) return value;
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return value;
  }

  // BigInt (typeof check before object checks)
  if (typeof value === 'bigint') {
    const ser = options?.customSerializers?.get('BigInt') ?? BUILTIN_SERIALIZERS.get('BigInt')!;
    return ser(value);
  }

  // Date
  if (value instanceof Date) {
    const ser = options?.customSerializers?.get('Date') ?? BUILTIN_SERIALIZERS.get('Date')!;
    return ser(value);
  }

  // Map
  if (value instanceof Map) {
    const serializedEntries = [...value.entries()].map(
      ([k, v]) => [serializeValue(k, options), serializeValue(v, options)]
    );
    return { __serde_type: 'Map', value: serializedEntries };
  }

  // Set
  if (value instanceof Set) {
    const serializedValues = [...value].map(v => serializeValue(v, options));
    return { __serde_type: 'Set', value: serializedValues };
  }

  // RegExp
  if (value instanceof RegExp) {
    const ser = options?.customSerializers?.get('RegExp') ?? BUILTIN_SERIALIZERS.get('RegExp')!;
    return ser(value);
  }

  // Arrays
  if (Array.isArray(value)) {
    return value.map(item => serializeValue(item, options));
  }

  // Plain objects -- recurse into values
  if (typeof value === 'object') {
    const result: Record<string, any> = {};
    for (const [key, val] of Object.entries(value)) {
      result[key] = serializeValue(val, options);
    }
    return result;
  }

  // Fallback: return as-is (functions, symbols, etc. will be lost in JSON anyway)
  return value;
}

/**
 * Recursively deserialize a value, restoring tagged values to their original types.
 */
export function deserializeValue(value: any, options?: SerdeOptions): any {
  if (value === null || value === undefined) return value;
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    return value;
  }

  // Arrays
  if (Array.isArray(value)) {
    return value.map(item => deserializeValue(item, options));
  }

  // Tagged values
  if (isTaggedValue(value)) {
    const type = value.__serde_type;
    const customDeser = options?.customDeserializers?.get(type);
    if (customDeser) {
      return customDeser(deserializeValue(value.value, options));
    }
    const builtinDeser = BUILTIN_DESERIALIZERS.get(type);
    if (builtinDeser) {
      return builtinDeser(deserializeValue(value.value, options));
    }
    // Unknown tagged type -- return as-is (don't strip the tag)
    return value;
  }

  // Plain objects -- recurse
  if (typeof value === 'object') {
    const result: Record<string, any> = {};
    for (const [key, val] of Object.entries(value)) {
      result[key] = deserializeValue(val, options);
    }
    return result;
  }

  return value;
}

/**
 * Serialize an entire state data record.
 */
export function serializeState(
  data: Record<string, any>,
  options?: SerdeOptions
): Record<string, any> {
  return serializeValue(data, options) as Record<string, any>;
}

/**
 * Deserialize an entire state data record.
 */
export function deserializeState(
  data: Record<string, any>,
  options?: SerdeOptions
): Record<string, any> {
  return deserializeValue(data, options) as Record<string, any>;
}
