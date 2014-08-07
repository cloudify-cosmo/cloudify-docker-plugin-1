# coding=utf-8
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.


import psutil
import select
import subprocess
import time


def _read_streams(ctx, pipe, timeout):
    ctx.logger.info('Waiting for subprocess to finish...')
    fds = {
        pipe.stdout.fileno(): {
            'file': pipe.stdout,
            'output': '',
            'eof': False
        },
        pipe.stderr.fileno(): {
            'file': pipe.stderr,
            'output': '',
            'eof': False
        }
    }
    while True:
        read_fds = [fds[fd]['file'] for fd in fds]
        read_fds, _, _ = select.select(read_fds, [], [], timeout)
        if not read_fds:
            ctx.logger.error('Subprocess hung up')
            hung_up = True
            break
        for fd in read_fds:
            output = fd.read(1)
            fds[fd.fileno()]['output'] += output
            fds[fd.fileno()]['eof'] = (output == '')
        if all(fds[fd]['eof'] for fd in fds):
            ctx.logger.info('Subprocess finished')
            hung_up = False
            break
    return (
        fds[pipe.stdout.fileno()]['output'],
        fds[pipe.stderr.fileno()]['output'],
        not hung_up
    )


def _manually_clean_up(ctx, pipe, waiting_for_output, timeout_terminate):
    ctx.logger.info('Terminating process')
    pipe.terminate()
    time_no_terminate = 0
    process = psutil.Process(pipe.pid)
    while (
            time_no_terminate < timeout_terminate and
            process.status() != psutil.STATUS_ZOMBIE
    ):
        time.sleep(1)
        process = psutil.Process(pipe.pid)
        time_no_terminate += 1

    stdout, stderr, success = _read_streams(ctx, pipe, waiting_for_output)
    if process.status() == psutil.STATUS_ZOMBIE:
        ctx.logger.info('Process terminated')
    else:
        ctx.logger.info('Killing process')
        pipe.kill()
        stdout += pipe.stdout.read()
        stderr += pipe.stderr.read()
    pipe.wait()
    return stdout, stderr


def _clean_up(ctx, pipe, success, waiting_for_output, timeout_terminate):
    ctx.logger.info('Cleaning up')
    stdout, stderr = '', ''
    if success:
        pipe.wait()
    else:
        stdout, stderr = _manually_clean_up(
            ctx,
            pipe,
            waiting_for_output,
            timeout_terminate,
        )
    pipe.stdout.close()
    pipe.stderr.close()
    ctx.logger.info('Cleaned up')
    return stdout, stderr


def run_process(
        ctx,
        process,
        waiting_for_output,
        timeout_terminate
):
    ctx.logger.info('Starting process')
    pipe = subprocess.Popen(
        process.split(' '),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    stdout, stderr, success = _read_streams(ctx, pipe, waiting_for_output)
    new_stdout, new_stderr = _clean_up(
        ctx,
        pipe,
        success,
        waiting_for_output,
        timeout_terminate
    )
    stdout += new_stdout
    stderr += new_stderr
    ctx.logger.info('Finishing process')
    return pipe.returncode, stdout, stderr
