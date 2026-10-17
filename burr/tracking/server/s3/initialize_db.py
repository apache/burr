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

from pathlib import Path

from tortoise import Tortoise, run_async

from burr.tracking.server.s3 import settings


async def connect():
    db_path = Path(settings.DB_PATH).expanduser()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    await Tortoise.init(
        config=settings.TORTOISE_ORM,
    )


#
async def first_time_init():
    await connect()
    # Generate the schema
    await Tortoise.generate_schemas()


if __name__ == "__main__":
    # db_path = sys.argv[1]
    run_async(first_time_init())
