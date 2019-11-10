#!/usr/bin/python

import os
import os.path
import runtime
import sys

from options import *
from os_utils import *
from os.path import join as path_join


runtime_targets = ['runtime', 'runtime-threads', 'runtime-dynamic']
cross_targets = [] # ['cross'] # TODO
cross_mxe_targets = [] # ['cross-win'] # TODO


def is_cross(target) -> bool:
    return target in cross_targets or is_cross_mxe(target)


def is_cross_mxe(target) -> bool:
    return target in cross_mxe_targets


def setup_wasm_target_template(env: dict, opts: RuntimeOpts, target: str):
    extra_target_envs = {
        'runtime-threads': {
            'wasm_runtime-threads_CFLAGS': ['-s', 'USE_PTHREADS=1', '-pthread'],
            'wasm_runtime-threads_CXXFLAGS': ['-s', 'USE_PTHREADS=1', '-pthread']
        },
        'runtime-dynamic': {
            'wasm_runtime-dynamic_CFLAGS': ['-s', 'WASM_OBJECT_FILES=0'],
            'wasm_runtime-dynamic_CXXFLAGS': ['-s', 'WASM_OBJECT_FILES=0']
        }
    }

    if target in extra_target_envs:
        env.update(extra_target_envs[target])

    CFLAGS = ['-fexceptions']
    CFLAGS += ['-Os', '-g'] if opts.release else ['-O0', '-ggdb3', '-fno-omit-frame-pointer']
    CXXFLAGS = CFLAGS + ['-s', 'DISABLE_EXCEPTION_CATCHING=0']

    CONFIGURE_FLAGS = [
        '--disable-mcs-build',
        '--disable-nls',
        '--disable-boehm',
        '--disable-btls',
        '--with-lazy-gc-thread-creation=yes',
        '--with-libgc=none',
        '--disable-executables',
        '--disable-support-build',
        '--disable-visibility-hidden',
        '--enable-maintainer-mode',
        '--enable-minimal=ssa,com,jit,reflection_emit_save,portability,assembly_remapping,attach,verifier,full_messages,appdomains,security,sgen_marksweep_conc,sgen_split_nursery,sgen_gc_bridge,logging,remoting,shared_perfcounters,sgen_debug_helpers,soft_debug,interpreter,assert_messages,cleanup,mdb,gac',
        '--host=wasm32',
        '--enable-llvm-runtime',
        '--enable-icall-export',
        '--disable-icall-tables',
        '--disable-crash-reporting',
        '--with-bitcode=yes'
    ]

    CONFIGURE_FLAGS += ['--enable-cxx'] if opts.enable_cxx else []

    CONFIGURE_FLAGS += [
        '--cache-file=%s/wasm-%s-%s.config.cache' % (opts.configure_dir, target, opts.configuration),
        '--prefix=%s/wasm-%s-%s' % (opts.install_dir, target, opts.configuration),
        'CFLAGS=%s %s' % (' '.join(CFLAGS), env.get('wasm_%s_CFLAGS' % target, '')),
        'CXXFLAGS=%s %s' % (' '.join(CXXFLAGS), env.get('$$(wasm_%s_CXXFLAGS' % target, ''))
    ]

    CONFIGURE_FLAGS += env.get('wasm_%s_CONFIGURE_FLAGS' % target, [])

    env['_wasm_%s_CONFIGURE_FLAGS' % target] = CONFIGURE_FLAGS
    env['_wasm_%s_AC_VARS' % target] = ['ac_cv_func_shm_open_working_with_mmap=no']


def wasm_run_configure(env: dict, opts: RuntimeOpts, product: str, target: str, emsdk_root: str):
    build_dir = path_join(opts.configure_dir, '%s-%s-%s' % (product, target, opts.configuration))
    mkdir_p(build_dir)

    def str_dict_val(val):
        if isinstance(val, list):
            return ' '.join(val) # Don't need to surround with quotes
        return val

    ac_vars = env['_%s_%s_AC_VARS' % (product, target)]
    configure_flags = env['_%s_%s_CONFIGURE_FLAGS' % (product, target)]

    configure = path_join(opts.mono_source_root, 'configure')
    configure_args = ac_vars + configure_flags

    configure_env = os.environ.copy()

    target_extra_path = env.get('_%s-%s_PATH' % (product, target), '')
    if target_extra_path:
        configure_env['PATH'] += ':' + target_extra_path

    configure_env['PATH'] = emsdk_root + ':' + configure_env['PATH']

    run_command('emconfigure', args=[configure] + configure_args, cwd=build_dir, env=configure_env, name='configure')


def configure(opts: RuntimeOpts, product: str, target: str):
    env = {}

    if is_cross(target):
        if is_cross_mxe(target):
            raise RuntimeError('TODO')
        else:
            raise RuntimeError('TODO')
    else:
        setup_wasm_target_template(env, opts, target)

    if not os.path.isfile(path_join(opts.mono_source_root, 'configure')):
        runtime.run_autogen(opts)

    wasm_run_configure(env, opts, product, target, get_emsdk_root())


def make(opts: RuntimeOpts, product: str, target: str):
    env = {}

    emsdk_root = get_emsdk_root()

    build_dir = path_join(opts.configure_dir, '%s-%s-%s' % (product, target, opts.configuration))
    install_dir = path_join(opts.install_dir, '%s-%s-%s' % (product, target, opts.configuration))

    make_args = ['-C', build_dir]
    make_args += ['V=1'] if opts.verbose_make else []

    make_env = os.environ.copy()
    make_env['PATH'] = emsdk_root + ':' + make_env['PATH']

    run_command('emmake', args=['make'] + make_args, env=make_env, name='make')

    run_command('make', args=['-C', '%s/mono' % build_dir, 'install'], name='make install mono')

    # Copy support headers

    from shutil import copy

    headers = ['crc32.h', 'deflate.h', 'inffast.h', 'inffixed.h', 'inflate.h', 'inftrees.h', 'trees.h', 'zconf.h', 'zlib.h', 'zutil.h']
    src_support_dir = '%s/support' % opts.mono_source_root
    dst_support_dir = '%s/include/support' % install_dir

    mkdir_p(dst_support_dir)

    for header in headers:
        copy(path_join(src_support_dir, header), dst_support_dir)

    # Copy wasm src files

    wasm_src_files = [
        'driver.c',
        'zlib-helper.c',
        'corebindings.c',
        'pinvoke-tables-default.h',
        'pinvoke-tables-default-netcore.h',
        'library_mono.js',
        'binding_support.js',
        'dotnet_support.js'
    ]

    dst_wasm_src_dir = path_join(install_dir, 'src')

    mkdir_p(dst_wasm_src_dir)

    for wasm_src_file in wasm_src_files:
        copy(path_join(opts.mono_source_root, 'sdks/wasm/src', wasm_src_file), dst_wasm_src_dir)


def clean(opts: RuntimeOpts, product: str, target: str):
    rm_rf(
        path_join(opts.configure_dir, '%s-%s-%s' % (product, target, opts.configuration)),
        path_join(opts.configure_dir, '%s-%s-%s.config.cache' % (product, target, opts.configuration)),
        path_join(opts.install_dir, '%s-%s-%s' % (product, target, opts.configuration))
    )


def main(raw_args):
    import cmd_utils
    from collections import OrderedDict
    from typing import Callable

    target_shortcuts = {'all-runtime': runtime_targets}

    target_values = runtime_targets + cross_targets + cross_mxe_targets + list(target_shortcuts)

    actions = OrderedDict()
    actions['configure'] = configure
    actions['make'] = make
    actions['clean'] = clean

    parser = cmd_utils.build_arg_parser(description='Builds the Mono runtime for WebAssembly')

    emsdk_root_default = os.environ.get('EMSDK_ROOT', default='')

    default_help = 'default: %(default)s'

    parser.add_argument('action', choices=['configure', 'make', 'clean'])
    parser.add_argument('--target', choices=target_values, action='append', required=True)

    cmd_utils.add_runtime_arguments(parser, default_help)

    args = parser.parse_args(raw_args)

    input_action = args.action
    input_targets = args.target

    opts = runtime_opts_from_args(args)

    if not os.path.isdir(opts.mono_source_root):
        print('Mono sources directory not found: ' + opts.mono_source_root)
        sys.exit(1)

    targets = cmd_utils.expand_input_targets(input_targets, target_shortcuts)
    action = actions[input_action]

    try:
        for target in targets:
            action(opts, 'wasm', target)
    except BuildError as e:
        sys.exit(e.message)


if __name__ == '__main__':
    from sys import argv
    main(argv[1:])