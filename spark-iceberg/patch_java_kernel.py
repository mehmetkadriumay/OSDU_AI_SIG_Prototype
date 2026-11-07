"""Add the --add-opens flags Spark needs on Java 17 to the IJava kernelspec."""
import json, subprocess
specs = json.loads(subprocess.check_output(["jupyter", "kernelspec", "list", "--json"]))["kernelspecs"]
if "java" in specs:
    path = specs["java"]["resource_dir"] + "/kernel.json"
    spec = json.load(open(path))
    pkgs = ["java.lang", "java.lang.invoke", "java.lang.reflect", "java.io", "java.net", "java.nio",
            "java.util", "java.util.concurrent", "java.util.concurrent.atomic", "jdk.internal.ref",
            "sun.nio.ch", "sun.nio.cs", "sun.security.action", "sun.util.calendar"]
    spec.setdefault("env", {})["JDK_JAVA_OPTIONS"] = " ".join(f"--add-opens=java.base/{p}=ALL-UNNAMED" for p in pkgs)
    json.dump(spec, open(path, "w"), indent=1)
    print("patched", path)
