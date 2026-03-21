/*
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

import { useQuery } from 'react-query';
import { DefaultService, Project } from '../../api';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '../common/table';
import { Loading } from '../common/loading';
import { DateDisplay } from '../common/dates';
import { Chip } from '../common/chip';
import { LinkText } from '../common/href';
import { Link, useNavigate } from 'react-router-dom';
import { FaRegEdit } from 'react-icons/fa';

/**
 * Table of a project list. Uses the tailwind catalyst component.
 * This does not load or fetch any data, just renders it
 */
export const ProjectListTable = (props: { projects: Project[]; includeAnnotations: boolean }) => {
  const navigate = useNavigate();
  const projectsCopy = [...props.projects];
  const projectsSorted = projectsCopy.sort((a, b) => {
    return a.last_written > b.last_written ? -1 : 1;
  });
  return (
    <Table>
      <TableHead>
        <TableRow>
          <TableHeader>Name</TableHeader>
          <TableHeader>Created</TableHeader>
          <TableHeader>Last Run</TableHeader>
          <TableHeader>Link</TableHeader>
          <TableHeader>App Runs</TableHeader>
          {props.includeAnnotations && <TableHeader className="w-10">Annotations</TableHeader>}
          <TableHeader></TableHeader>
        </TableRow>
      </TableHead>
      <TableBody>
        {projectsSorted.map((project) => {
          let projectName = project.name;
          const chipType =
            projectName.startsWith('demo:') || projectName.startsWith('demo_')
              ? 'demo'
              : projectName.startsWith('test:') || projectName.startsWith('test_')
                ? 'test'
                : undefined;
          if (chipType) {
            projectName = projectName.slice(5);
          }

          return (
            <TableRow
              key={project.id}
              className="hover:bg-gray-50 cursor-pointer"
              onClick={() => navigate(`/project/${project.id}`)}
            >
              <TableCell className="font-semibold text-gray-700">
                <div className="flex flex-row gap-2">
                  {chipType !== undefined && <Chip label={chipType} chipType={chipType}></Chip>}
                  {projectName}
                </div>
              </TableCell>
              <TableCell>
                <DateDisplay date={project.created} />
              </TableCell>
              <TableCell>
                <DateDisplay date={project.last_written} />
              </TableCell>
              <TableCell>
                <LinkText
                  href={project.uri}
                  text={project.uri.replace('https://github.com/apache/burr/tree/main/', '')}
                />
              </TableCell>
              <TableCell>{project.num_apps}</TableCell>
              {props.includeAnnotations && (
                <TableCell>
                  <Link to={`/annotations/${project.id}`}>
                    <FaRegEdit
                      className="hover:underline hover:scale-125"
                      onClick={(e) => {
                        navigate(`/annotations/${project.id}`);
                        e.stopPropagation();
                        e.preventDefault();
                      }}
                    ></FaRegEdit>
                  </Link>
                </TableCell>
              )}
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
};

/**
 * Container for the table -- fetches the data and passes it to the table
 */
export const ProjectList = () => {
  const { data, error } = useQuery('projects', DefaultService.getProjectsApiV0ProjectsGet);
  const { data: backendSpec } = useQuery(['backendSpec'], () =>
    DefaultService.getAppSpecApiV0MetadataAppSpecGet().then((response) => {
      return response;
    })
  );
  if (error) return <div>Error loading projects</div>;
  if (data === undefined || backendSpec === undefined) return <Loading />;
  return (
    <div className="">
      <ProjectListTable projects={data} includeAnnotations={backendSpec?.supports_annotations} />
    </div>
  );
};
