/**
 * Type Testing Framework
 * 
 * Uses TypeScript Compiler API to validate type tests.
 * Each test file has JSON metadata on line 1, followed by "// START_TEST", then TypeScript code.
 */

import * as ts from 'typescript';
import * as fs from 'fs';
import * as path from 'path';

export interface TestMetadata {
  type: 'pass' | 'fail';
  errorCode?: string;      // e.g. "TS2769" - required for "fail"
  errorPattern?: string;   // Substring to match - required for "fail"
  category: string;        // e.g. "actions", "state", "graph"
  description?: string;    // Human-readable description
}

export interface TestResult {
  filepath: string;
  passed: boolean;
  message: string;
  duration: number;
  metadata: TestMetadata;
}

/**
 * Parse a test file into metadata and code
 * 
 * Expected format:
 * // Optional: Apache license header (ignored)
 * export const TEST_META = { type: "fail", ... };
 * // START_TEST
 * ... TypeScript code ...
 */
export function parseTestFile(filepath: string): { metadata: TestMetadata; code: string } {
  const content = fs.readFileSync(filepath, 'utf-8');
  
  // Find TEST_META export (skip any comments/license headers before it)
  const metaMatch = content.match(/export\s+const\s+TEST_META\s*=\s*({[^;]+});/s);
  if (!metaMatch) {
    throw new Error(
      `❌ INVALID TEST FILE: ${filepath}\n` +
      `   Must export TEST_META constant.\n` +
      `   Expected format:\n` +
      `   export const TEST_META = { type: "pass", category: "...", ... };`
    );
  }
  
  // Parse the metadata object
  const metadataStr = metaMatch[1];
  let metadata: TestMetadata;
  try {
    // Use Function constructor to safely eval the object literal
    metadata = new Function(`return ${metadataStr}`)();
  } catch (e) {
    throw new Error(
      `❌ INVALID TEST_META in ${filepath}\n` +
      `   Failed to parse metadata object: ${e instanceof Error ? e.message : String(e)}\n` +
      `   Metadata string: ${metadataStr.substring(0, 100)}...`
    );
  }
  
  // Validate metadata structure
  if (!metadata.type) {
    throw new Error(
      `❌ INVALID TEST_META in ${filepath}\n` +
      `   Missing required field: "type" (must be "pass" or "fail")`
    );
  }
  
  if (metadata.type !== 'pass' && metadata.type !== 'fail') {
    throw new Error(
      `❌ INVALID TEST_META in ${filepath}\n` +
      `   Invalid type: "${metadata.type}" (must be "pass" or "fail")`
    );
  }
  
  if (!metadata.category) {
    throw new Error(
      `❌ INVALID TEST_META in ${filepath}\n` +
      `   Missing required field: "category" (e.g. "actions", "state", "graph")`
    );
  }
  
  if (metadata.type === 'fail') {
    if (!metadata.errorCode) {
      throw new Error(
        `❌ INVALID TEST_META in ${filepath}\n` +
        `   "fail" tests require "errorCode" field (e.g. "TS2769")`
      );
    }
    if (!metadata.errorPattern) {
      throw new Error(
        `❌ INVALID TEST_META in ${filepath}\n` +
        `   "fail" tests require "errorPattern" field (substring to match in error message)`
      );
    }
    if (!metadata.errorCode.match(/^TS\d+$/)) {
      throw new Error(
        `❌ INVALID TEST_META in ${filepath}\n` +
        `   Invalid errorCode format: "${metadata.errorCode}" (must be like "TS2769")`
      );
    }
  }
  
  // Find START_TEST marker
  const startTestIndex = content.indexOf('// START_TEST');
  if (startTestIndex === -1) {
    throw new Error(
      `❌ INVALID TEST FILE: ${filepath}\n` +
      `   Missing "// START_TEST" marker.\n` +
      `   This marker separates metadata from test code.`
    );
  }
  
  // Extract code after START_TEST (this is what gets compiled)
  const code = content.substring(startTestIndex + '// START_TEST'.length).trim();
  
  if (code.length === 0) {
    throw new Error(
      `❌ INVALID TEST FILE: ${filepath}\n` +
      `   No test code found after "// START_TEST" marker.`
    );
  }
  
  return { metadata, code };
}

/**
 * Compile TypeScript code and return diagnostics
 */
export function compileTypeScriptCode(code: string, testFilePath: string): ts.Diagnostic[] {
  // Get TypeScript config from the project root
  const projectRoot = path.resolve(__dirname, '../../..');
  const configPath = ts.findConfigFile(projectRoot, ts.sys.fileExists, 'tsconfig.json');
  if (!configPath) {
    throw new Error('Could not find tsconfig.json');
  }
  
  const configFile = ts.readConfigFile(configPath, ts.sys.readFile);
  const compilerOptions = ts.parseJsonConfigFileContent(
    configFile.config,
    ts.sys,
    path.dirname(configPath)
  ).options;
  
  // Override some options for testing
  compilerOptions.noEmit = true;
  compilerOptions.skipLibCheck = true;
  compilerOptions.noUnusedLocals = false;  // Don't complain about unused vars in tests
  compilerOptions.noUnusedParameters = false;
  
  // Use the actual test file path so imports resolve correctly
  const virtualFileName = testFilePath.replace(/\.ts$/, '.virtual.ts');
  
  // Create a virtual source file with proper path
  const sourceFile = ts.createSourceFile(
    virtualFileName,
    code,
    ts.ScriptTarget.Latest,
    true
  );
  
  // Create a compiler host that includes our virtual file
  const host = ts.createCompilerHost(compilerOptions);
  const originalGetSourceFile = host.getSourceFile;
  
  host.getSourceFile = (fileName, languageVersion, onError, shouldCreateNewSourceFile) => {
    // Use our virtual file
    if (fileName === virtualFileName) {
      return sourceFile;
    }
    // Resolve other imports normally from filesystem
    return originalGetSourceFile.call(host, fileName, languageVersion, onError, shouldCreateNewSourceFile);
  };
  
  // Include both our virtual file and the main index file so imports resolve
  const indexPath = path.resolve(projectRoot, 'src/index.ts');
  const program = ts.createProgram([virtualFileName, indexPath], compilerOptions, host);
  const diagnostics = ts.getPreEmitDiagnostics(program, sourceFile);
  
  // Filter diagnostics to only those in our test file
  return diagnostics.filter(d => {
    const file = d.file;
    if (!file) return false;  // Skip global diagnostics
    return file.fileName === virtualFileName;
  });
}

/**
 * Validate test results against metadata expectations
 */
export function validateTest(
  diagnostics: ts.Diagnostic[],
  metadata: TestMetadata
): { passed: boolean; message: string } {
  if (metadata.type === 'pass') {
    // Should have no errors
    if (diagnostics.length === 0) {
      return { passed: true, message: '✓ Compiled successfully' };
    } else {
      const errors = diagnostics.map(d => {
        const message = ts.flattenDiagnosticMessageText(d.messageText, '\n');
        return `  TS${d.code}: ${message}`;
      }).join('\n');
      return {
        passed: false,
        message: `✗ Expected to pass but got errors:\n${errors}`
      };
    }
  } else {
    // Should have specific error
    if (diagnostics.length === 0) {
      return {
        passed: false,
        message: `✗ Expected error ${metadata.errorCode} but code compiled successfully`
      };
    }
    
    // Check if we have the expected error code
    const expectedCode = parseInt(metadata.errorCode!.replace('TS', ''), 10);
    const hasExpectedError = diagnostics.some(d => d.code === expectedCode);
    
    if (!hasExpectedError) {
      const actualErrors = diagnostics.map(d => `TS${d.code}`).join(', ');
      return {
        passed: false,
        message: `✗ Expected error ${metadata.errorCode} but got: ${actualErrors}`
      };
    }
    
    // Check if error message matches pattern
    const matchingDiagnostic = diagnostics.find(d => {
      if (d.code !== expectedCode) return false;
      const message = ts.flattenDiagnosticMessageText(d.messageText, '\n');
      return message.includes(metadata.errorPattern!);
    });
    
    if (!matchingDiagnostic) {
      const actualMessages = diagnostics
        .filter(d => d.code === expectedCode)
        .map(d => ts.flattenDiagnosticMessageText(d.messageText, '\n'))
        .join('\n  ');
      return {
        passed: false,
        message: `✗ Error ${metadata.errorCode} found but message doesn't match pattern "${metadata.errorPattern}"\nActual messages:\n  ${actualMessages}`
      };
    }
    
    return {
      passed: true,
      message: `✓ Got expected error ${metadata.errorCode}: ${metadata.errorPattern}`
    };
  }
}

/**
 * Run a single test file
 */
export function runTestFile(filepath: string): TestResult {
  const startTime = Date.now();
  
  try {
    const { metadata, code } = parseTestFile(filepath);
    const diagnostics = compileTypeScriptCode(code, filepath);
    const validation = validateTest(diagnostics, metadata);
    
    return {
      filepath,
      passed: validation.passed,
      message: validation.message,
      duration: Date.now() - startTime,
      metadata
    };
  } catch (error) {
    return {
      filepath,
      passed: false,
      message: `✗ Test execution error: ${error instanceof Error ? error.message : String(error)}`,
      duration: Date.now() - startTime,
      metadata: { type: 'pass', category: 'unknown' }
    };
  }
}

/**
 * Discover all test files in a directory recursively
 */
export function discoverTestFiles(directory: string): string[] {
  const files: string[] = [];
  
  function walk(dir: string) {
    const entries = fs.readdirSync(dir, { withFileTypes: true });
    
    for (const entry of entries) {
      const fullPath = path.join(dir, entry.name);
      
      if (entry.isDirectory()) {
        // Skip framework files and node_modules
        if (entry.name !== 'node_modules' && entry.name !== 'dist') {
          walk(fullPath);
        }
      } else if (entry.isFile() && entry.name.endsWith('.ts') && !entry.name.includes('framework') && !entry.name.includes('runner')) {
        files.push(fullPath);
      }
    }
  }
  
  walk(directory);
  return files.sort();  // Lexical sort including directory path
}

/**
 * Run all tests in a directory using a single shared TypeScript Program
 * This is much faster than compiling each test separately
 */
export async function runAllTests(
  directory: string
): Promise<TestResult[]> {
  const testFiles = discoverTestFiles(directory);
  
  // Parse all test files first
  const parsedTests = testFiles.map(filepath => {
    try {
      const { metadata, code } = parseTestFile(filepath);
      return { filepath, metadata, code, error: null };
    } catch (error) {
      return {
        filepath,
        metadata: { type: 'pass' as const, category: 'unknown' },
        code: '',
        error: error instanceof Error ? error.message : String(error)
      };
    }
  });
  
  // Create a single TypeScript Program for all test files
  const diagnosticsByFile = compileAllTests(parsedTests);
  
  // Process results
  const results: TestResult[] = parsedTests.map((test) => {
    const testStartTime = Date.now();
    
    if (test.error) {
      return {
        filepath: test.filepath,
        passed: false,
        message: `✗ Test execution error: ${test.error}`,
        duration: 0,
        metadata: test.metadata
      };
    }
    
    const diagnostics = diagnosticsByFile.get(test.filepath) || [];
    const validation = validateTest(diagnostics, test.metadata);
    
    return {
      filepath: test.filepath,
      passed: validation.passed,
      message: validation.message,
      duration: Date.now() - testStartTime,
      metadata: test.metadata
    };
  });
  
  return results;
}

/**
 * Compile all test files in a single TypeScript Program for performance
 */
function compileAllTests(
  tests: Array<{ filepath: string; code: string; metadata: TestMetadata; error: string | null }>
): Map<string, ts.Diagnostic[]> {
  // Get TypeScript config
  const projectRoot = path.resolve(__dirname, '../../..');
  const configPath = ts.findConfigFile(projectRoot, ts.sys.fileExists, 'tsconfig.json');
  if (!configPath) {
    throw new Error('Could not find tsconfig.json');
  }
  
  const configFile = ts.readConfigFile(configPath, ts.sys.readFile);
  const compilerOptions = ts.parseJsonConfigFileContent(
    configFile.config,
    ts.sys,
    path.dirname(configPath)
  ).options;
  
  // Override options for testing
  compilerOptions.noEmit = true;
  compilerOptions.skipLibCheck = true;
  compilerOptions.noUnusedLocals = false;
  compilerOptions.noUnusedParameters = false;
  
  // Create virtual file names and source files
  const virtualFiles = new Map<string, ts.SourceFile>();
  const fileToOriginal = new Map<string, string>();
  
  for (const test of tests) {
    if (test.error) continue;
    
    const virtualFileName = test.filepath.replace(/\.ts$/, '.virtual.ts');
    const sourceFile = ts.createSourceFile(
      virtualFileName,
      test.code,
      ts.ScriptTarget.Latest,
      true
    );
    virtualFiles.set(virtualFileName, sourceFile);
    fileToOriginal.set(virtualFileName, test.filepath);
  }
  
  // Create compiler host with all virtual files
  const host = ts.createCompilerHost(compilerOptions);
  const originalGetSourceFile = host.getSourceFile;
  
  host.getSourceFile = (fileName, languageVersion, onError, shouldCreateNewSourceFile) => {
    // Check if it's one of our virtual files
    if (virtualFiles.has(fileName)) {
      return virtualFiles.get(fileName)!;
    }
    // Otherwise load from filesystem
    return originalGetSourceFile.call(host, fileName, languageVersion, onError, shouldCreateNewSourceFile);
  };
  
  // Create single program with all test files
  const indexPath = path.resolve(projectRoot, 'src/index.ts');
  const allFiles = [indexPath, ...Array.from(virtualFiles.keys())];
  const program = ts.createProgram(allFiles, compilerOptions, host);
  
  // Extract diagnostics per test file
  const diagnosticsByFile = new Map<string, ts.Diagnostic[]>();
  
  for (const [virtualFileName, originalPath] of fileToOriginal.entries()) {
    const sourceFile = virtualFiles.get(virtualFileName);
    if (!sourceFile) continue;
    
    const diagnostics = ts.getPreEmitDiagnostics(program, sourceFile);
    
    // Filter to only diagnostics in this specific file
    const filtered = diagnostics.filter(d => {
      const file = d.file;
      if (!file) return false;
      return file.fileName === virtualFileName;
    });
    
    diagnosticsByFile.set(originalPath, filtered);
  }
  
  return diagnosticsByFile;
}

