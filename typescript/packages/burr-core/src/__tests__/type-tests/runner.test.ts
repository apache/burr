/**
 * Type Test Runner
 * 
 * This Jest test discovers and runs all type tests using the framework.
 * Each test file becomes a separate Jest test case.
 */

import { runAllTests, discoverTestFiles } from './framework';
import * as path from 'path';

// Support running a single test: TEST_FILE=actions/missing-writes.ts npm run test:types
const singleTestFile = process.env.TEST_FILE;

describe('Type Tests', () => {
  // Discover all test files first
  const testDir = __dirname;
  let testFiles = discoverTestFiles(testDir);
  
  // Filter to single test if requested
  if (singleTestFile) {
    testFiles = testFiles.filter(filepath => {
      const relativePath = path.relative(testDir, filepath);
      return relativePath === singleTestFile || relativePath.endsWith(singleTestFile);
    });
    
    if (testFiles.length === 0) {
      throw new Error(`No test file found matching: ${singleTestFile}`);
    }
    console.log(`\n🎯 Running single test: ${path.relative(testDir, testFiles[0])}\n`);
  }
  
  if (testFiles.length === 0) {
    test('no tests found', () => {
      throw new Error(`No type test files found in ${testDir}`);
    });
    return;
  }
  
  // Run all tests once before creating Jest test cases
  let allResults: Awaited<ReturnType<typeof runAllTests>>;
  
  beforeAll(async () => {
    const startTime = Date.now();
    allResults = await runAllTests(testDir);
    const duration = Date.now() - startTime;
    
    if (!singleTestFile) {
      console.log(`\n📊 Type Test Summary:`);
      console.log(`   Total: ${allResults.length} tests`);
      console.log(`   Duration: ${duration}ms`);
      
      // Group by category
      const byCategory = new Map<string, number>();
      allResults.forEach(r => {
        const count = byCategory.get(r.metadata.category) || 0;
        byCategory.set(r.metadata.category, count + 1);
      });
      
      console.log(`   Categories:`);
      Array.from(byCategory.entries()).sort().forEach(([cat, count]) => {
        console.log(`     - ${cat}: ${count} tests`);
      });
      console.log('');
    }
  }, 30000);  // 30s timeout for compilation
  
  // Create a Jest test for each type test file
  testFiles.forEach(filepath => {
    const relativePath = path.relative(testDir, filepath);
    
    test(relativePath, () => {
      // Find the result for this file
      const result = allResults.find(r => r.filepath === filepath);
      
      if (!result) {
        throw new Error(`No result found for ${relativePath}`);
      }
      
      // Jest assertion
      expect({
        passed: result.passed,
        message: result.message,
        duration: result.duration,
        category: result.metadata.category,
        description: result.metadata.description
      }).toEqual({
        passed: true,
        message: expect.stringContaining('✓'),
        duration: expect.any(Number),
        category: result.metadata.category,
        description: result.metadata.description
      });
    });
  });
});

