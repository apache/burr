// Licensed to the Apache Software Foundation (ASF) under one
// or more contributor license agreements.  See the NOTICE file
// distributed with this work for additional information
// regarding copyright ownership.  The ASF licenses this file
// to you under the Apache License, Version 2.0 (the
// "License"); you may not use this file except in compliance
// with the License.  You may obtain a copy of the License at
//
//   http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing,
// software distributed under the License is distributed on an
// "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
// KIND, either express or implied.  See the License for the
// specific language governing permissions and limitations
// under the License.

import {
  serializeValue,
  deserializeValue,
  serializeState,
  deserializeState,
} from '../serde';

describe('serde - primitives', () => {
  test('null and undefined pass through', () => {
    expect(serializeValue(null)).toBeNull();
    expect(serializeValue(undefined)).toBeUndefined();
    expect(deserializeValue(null)).toBeNull();
    expect(deserializeValue(undefined)).toBeUndefined();
  });

  test('strings, numbers, booleans pass through', () => {
    expect(serializeValue('hello')).toBe('hello');
    expect(serializeValue(42)).toBe(42);
    expect(serializeValue(true)).toBe(true);
    expect(deserializeValue('hello')).toBe('hello');
    expect(deserializeValue(42)).toBe(42);
    expect(deserializeValue(false)).toBe(false);
  });
});

describe('serde - Date', () => {
  test('round-trips Date', () => {
    const date = new Date('2025-01-15T10:30:00.000Z');
    const serialized = serializeValue(date);
    expect(serialized).toEqual({ __serde_type: 'Date', value: '2025-01-15T10:30:00.000Z' });
    const deserialized = deserializeValue(serialized);
    expect(deserialized).toBeInstanceOf(Date);
    expect(deserialized.toISOString()).toBe('2025-01-15T10:30:00.000Z');
  });
});

describe('serde - Map', () => {
  test('round-trips Map', () => {
    const map = new Map([['a', 1], ['b', 2]]);
    const serialized = serializeValue(map);
    expect(serialized.__serde_type).toBe('Map');
    const deserialized = deserializeValue(serialized);
    expect(deserialized).toBeInstanceOf(Map);
    expect(deserialized.get('a')).toBe(1);
    expect(deserialized.get('b')).toBe(2);
  });

  test('Map with nested complex values', () => {
    const map = new Map([['date', new Date('2025-01-01')]]);
    const serialized = serializeValue(map);
    const deserialized = deserializeValue(serialized);
    expect(deserialized.get('date')).toBeInstanceOf(Date);
  });
});

describe('serde - Set', () => {
  test('round-trips Set', () => {
    const set = new Set([1, 2, 3]);
    const serialized = serializeValue(set);
    expect(serialized.__serde_type).toBe('Set');
    const deserialized = deserializeValue(serialized);
    expect(deserialized).toBeInstanceOf(Set);
    expect(deserialized.has(1)).toBe(true);
    expect(deserialized.size).toBe(3);
  });
});

describe('serde - RegExp', () => {
  test('round-trips RegExp', () => {
    const regex = /foo.*bar/gi;
    const serialized = serializeValue(regex);
    expect(serialized).toEqual({
      __serde_type: 'RegExp',
      value: { source: 'foo.*bar', flags: 'gi' },
    });
    const deserialized = deserializeValue(serialized);
    expect(deserialized).toBeInstanceOf(RegExp);
    expect(deserialized.source).toBe('foo.*bar');
    expect(deserialized.flags).toBe('gi');
  });
});

describe('serde - BigInt', () => {
  test('round-trips BigInt', () => {
    const big = BigInt('9007199254740993');
    const serialized = serializeValue(big);
    expect(serialized).toEqual({ __serde_type: 'BigInt', value: '9007199254740993' });
    const deserialized = deserializeValue(serialized);
    expect(deserialized).toBe(BigInt('9007199254740993'));
  });
});

describe('serde - arrays', () => {
  test('recursively serializes array contents', () => {
    const arr = [1, new Date('2025-01-01'), 'hello'];
    const serialized = serializeValue(arr);
    expect(serialized[0]).toBe(1);
    expect(serialized[1].__serde_type).toBe('Date');
    expect(serialized[2]).toBe('hello');
    const deserialized = deserializeValue(serialized);
    expect(deserialized[1]).toBeInstanceOf(Date);
  });
});

describe('serde - nested objects', () => {
  test('recursively serializes object values', () => {
    const obj = {
      name: 'test',
      created: new Date('2025-01-01'),
      tags: new Set(['a', 'b']),
      nested: { deep: new Map([['k', 42]]) },
    };
    const serialized = serializeValue(obj);
    const deserialized = deserializeValue(serialized);
    expect(deserialized.name).toBe('test');
    expect(deserialized.created).toBeInstanceOf(Date);
    expect(deserialized.tags).toBeInstanceOf(Set);
    expect(deserialized.nested.deep).toBeInstanceOf(Map);
    expect(deserialized.nested.deep.get('k')).toBe(42);
  });
});

describe('serde - state helpers', () => {
  test('serializeState / deserializeState round-trip', () => {
    const state = {
      count: 42,
      label: 'test',
      timestamp: new Date('2025-06-01'),
      items: [1, 2, 3],
    };
    const serialized = serializeState(state);
    const deserialized = deserializeState(serialized);
    expect(deserialized.count).toBe(42);
    expect(deserialized.label).toBe('test');
    expect(deserialized.timestamp).toBeInstanceOf(Date);
    expect(deserialized.items).toEqual([1, 2, 3]);
  });
});

describe('serde - custom serializers', () => {
  test('custom serializer overrides built-in', () => {
    const options = {
      customSerializers: new Map([
        ['Date', (v: Date) => ({ __serde_type: 'Date', value: v.getTime() })],
      ]),
      customDeserializers: new Map([
        ['Date', (v: number) => new Date(v)],
      ]),
    };
    const date = new Date('2025-01-01T00:00:00.000Z');
    const serialized = serializeValue(date, options);
    expect(serialized.value).toBe(date.getTime());
    const deserialized = deserializeValue(serialized, options);
    expect(deserialized).toBeInstanceOf(Date);
    expect(deserialized.getTime()).toBe(date.getTime());
  });
});

describe('serde - unknown tagged types', () => {
  test('unknown tagged value is returned as-is', () => {
    const tagged = { __serde_type: 'FutureType', value: { foo: 'bar' } };
    const result = deserializeValue(tagged);
    expect(result).toEqual(tagged);
  });
});
