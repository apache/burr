# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

"""
Vercel Serverless Function for counter application
Endpoint: /api/counter
"""
from http.server import BaseHTTPRequestHandler
import json
from app import counter_app


class handler(BaseHTTPRequestHandler):
    """Vercel Serverless Function handler.

    This class handles HTTP requests for the counter API endpoint.
    Must inherit from BaseHTTPRequestHandler to work with Vercel's Python runtime.
    """

    def do_POST(self):
        """Handle POST requests to increment counter.

        Expects JSON body with 'number' field indicating count limit.
        Returns serialized application state on success.
        """
        try:
            # Read request body
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)

            # Parse JSON payload
            data = json.loads(body.decode('utf-8'))

            # Extract parameter (equivalent to Lambda's event["body"]["number"])
            count_up_to = int(data.get("number", 0))

            # Validate input
            if count_up_to <= 0:
                self.send_error_response(400, "number must be greater than 0")
                return

            # Execute business logic (identical to Lambda implementation)
            app = counter_app.application(count_up_to)
            action, result, state = app.run(halt_after=["result"])

            # Return success response with serialized state
            self.send_json_response(200, state.serialize())
            
        except json.JSONDecodeError:
            self.send_error_response(400, "Invalid JSON format")
        except ValueError as e:
            self.send_error_response(400, f"Invalid number format: {str(e)}")
        except KeyError as e:
            self.send_error_response(400, f"Missing required field: {str(e)}")
        except Exception as e:
            # Log error for debugging
            print(f"Error in counter handler: {str(e)}")
            import traceback
            traceback.print_exc()
            self.send_error_response(500, "Internal server error")

    def do_GET(self):
        """Handle GET requests - not allowed.

        Returns 405 Method Not Allowed error.
        """
        self.send_error_response(405, "Only POST method is allowed")

    def do_PUT(self):
        """Handle PUT requests - not allowed.

        Returns 405 Method Not Allowed error.
        """
        self.send_error_response(405, "Only POST method is allowed")

    def do_DELETE(self):
        """Handle DELETE requests - not allowed.

        Returns 405 Method Not Allowed error.
        """
        self.send_error_response(405, "Only POST method is allowed")

    def send_json_response(self, status_code, data):
        """Send JSON response to client.

        Args:
            status_code: HTTP status code
            data: Response data (dict, list, or any JSON-serializable object)
        """
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        
        if isinstance(data, (dict, list)):
            response_body = json.dumps(data, ensure_ascii=False)
        else:
            response_body = str(data)
        
        self.wfile.write(response_body.encode('utf-8'))
    
    def send_error_response(self, status_code, message):
        """Send error response to client.

        Args:
            status_code: HTTP error status code
            message: Error message string to include in response body
        """
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        
        error_body = json.dumps({'error': message})
        self.wfile.write(error_body.encode('utf-8'))

