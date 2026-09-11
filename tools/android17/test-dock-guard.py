#!/usr/bin/env python3
"""Compile the real dock guard with minimal task stubs and test its contract."""
from pathlib import Path
import re
import subprocess
import sys
import tempfile

source = Path(sys.argv[1]).read_text()
compiler = Path(sys.argv[2]).resolve()
guard = re.search(r'if \((!isMediaApp && isFocusedFullScreenTask\(componentName.packageName\))\) \{\s*return', source)
assert guard, 'Missing non-media focused/full-screen early-return guard'
helper = re.search(r'    private fun isFocusedFullScreenTask\(packageName: String\): Boolean \{.*?\n    \}', source, re.S)
assert helper, 'Missing focused/full-screen predicate'
program = '''
data class Component(val packageName: String)
data class Task(val isFocused: Boolean, val windowingMode: Int, val topActivity: Component?)
class Model(val tasks: List<Task>) { fun getRunningTasks() = tasks }
class Controller(val dockViewModel: Model) {
HELPER
    fun wouldLaunch(componentName: Component, isMediaApp: Boolean) = !(GUARD)
}
fun main() {
    val app = Component("net.osmand.dev")
    fun launch(tasks: List<Task>, media: Boolean = false) = Controller(Model(tasks)).wouldLaunch(app, media)
    check(launch(emptyList()))
    check(!launch(listOf(Task(true, 1, app))))
    check(launch(listOf(Task(true, 1, app)), true))
    check(launch(listOf(Task(false, 1, app))))
    check(launch(listOf(Task(true, 6, app))))
    check(launch(listOf(Task(true, 1, Component("different.app")))))
    check(launch(listOf(Task(true, 1, null))))
    check(!launch(listOf(Task(false, 6, null), Task(true, 1, app))))
    println("PASS: 8 real dock-guard contract cases")
}
'''.replace('HELPER', helper.group(0)).replace('GUARD', guard.group(1))
with tempfile.TemporaryDirectory(prefix='caramel-dock-guard-') as directory:
    root = Path(directory)
    kotlin = root / 'DockGuardTest.kt'
    kotlin.write_text(program)
    subprocess.run([str(compiler), str(kotlin), '-include-runtime', '-d', str(root / 'test.jar')], check=True)
    subprocess.run(['java', '-jar', str(root / 'test.jar')], check=True)
