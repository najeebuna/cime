import glob
from pathlib import Path

from CIME.utils import safe_copy
from CIME.XML.standard_module_setup import *
from CIME.XML.env_build import EnvBuild
from CIME.XML.env_mach_pes import EnvMachPes
from CIME.XML.env_case import EnvCase
from CIME.XML.env_batch import EnvBatch
from CIME.XML.generic_xml import GenericXML

logger = logging.getLogger(__name__)


LOCKED_DIR = "LockedFiles"


def lock_file(filename, caseroot, newname=None):
    expect("/" not in filename, "Please just provide basename of locked file")

    if newname is None:
        newname = filename

    fulllockdir = os.path.join(caseroot, LOCKED_DIR)

    if not os.path.exists(fulllockdir):
        os.mkdir(fulllockdir)

    logging.debug("Locking file {}".format(filename))

    # JGF: It is extremely dangerous to alter our database (xml files) without
    # going through the standard API. The copy below invalidates all existing
    # GenericXML instances that represent this file and all caching that may
    # have involved this file. We should probably seek a safer way of locking
    # files.
    safe_copy(os.path.join(caseroot, filename), os.path.join(fulllockdir, newname))

    GenericXML.invalidate(os.path.join(fulllockdir, newname))


def unlock_file(filename, caseroot):
    expect("/" not in filename, "Please just provide basename of locked file")

    locked_path = os.path.join(caseroot, LOCKED_DIR, filename)

    if os.path.exists(locked_path):
        os.remove(locked_path)

    logging.debug("Unlocking file {}".format(filename))


def is_locked(filename, caseroot):
    expect("/" not in filename, "Please just provide basename of locked file")

    return os.path.exists(os.path.join(caseroot, LOCKED_DIR, filename))


def check_lockedfiles(case, skip=None):
    """
    Check that all lockedfiles match what's in case

    If caseroot is not specified, it is set to the current working directory
    """
    if skip is None:
        skip = []
    elif isinstance(skip, str):
        skip = [skip]

    caseroot = case.get_value("CASEROOT")

    lockedfiles = glob.glob(os.path.join(caseroot, LOCKED_DIR, "*.xml"))

    for file_path in lockedfiles:
        filename = os.path.basename(file_path)

        # Skip files used for tests e.g. env_mach_pes.ERP1.xml or included in skip list
        if filename.count(".") > 1 or any([filename.startswith(x) for x in skip]):
            continue

        env_name, diff = diff_lockedfile(case, caseroot, filename)

        if diff:
            check_diff(case, filename, env_name, diff)


def check_lockedfile(case, filebase):
    caseroot = case.get_value("CASEROOT")

    env_name, diff = diff_lockedfile(case, caseroot, filebase)

    if diff:
        check_diff(case, filebase, env_name, diff)


def diff_lockedfile(case, caseroot, filename):
    env_name = filename.split(".")[0]

    case_file = Path(caseroot, filename)

    locked_file = case_file.parent / LOCKED_DIR / filename

    if not locked_file.is_file():
        return env_name, {}

    if env_name == "env_build":
        l_env = case.get_env("build")
        r_env = EnvBuild(caseroot, str(locked_file), read_only=True)
    elif env_name == "env_mach_pes":
        l_env = case.get_env("mach_pes")
        r_env = EnvMachPes(
            caseroot,
            str(locked_file),
            components=case.get_values("COMP_CLASSES"),
            read_only=True,
        )
    elif env_name == "env_case":
        l_env = case.get_env("case")
        r_env = EnvCase(caseroot, str(locked_file), read_only=True)
    elif env_name == "env_batch":
        l_env = case.get_env("batch")
        r_env = EnvBatch(caseroot, str(locked_file), read_only=True)
    else:
        logger.warning(
            "Locked XML file {!r} is not currently being handled".format(filename)
        )

        return env_name, {}

    return env_name, l_env.compare_xml(r_env)


def check_diff(case, filename, env_name, diff):
    logger.warning("Detected diff in locked file {!r}".format(filename))

    # Remove BUILD_COMPLETE, invalid entry in diff
    diff.pop("BUILD_COMPLETE", None)

    # List differences
    for key, value in diff.items():
        logger.warning(
            "\t{!r} has changed from {!r} to {!r}".format(key, value[1], value[0])
        )

    if env_name == "env_case":
        expect(
            False,
            f"Cannot change `env_case.xml`, please restore origin {filename!r}",
        )
    elif env_name == "env_build":
        toggle_build_status = True if diff else False

        if toggle_build_status:
            logger.warning("Setting 'BUILD_COMPLETE' to False")

            case.set_value("BUILD_COMPLETE", False)

            build_status = 1

            if "PIO_VERSION" in diff:
                build_status = 2

                logging.critical(
                    "Changing 'PIO_VERSION' requires running `./case.build --clean-all` to rebuild"
                )

            case.set_value("BUILD_STATUS", build_status)
    elif env_name == "env_batch":
        expect(
            False,
            "Batch configuration has changed, please run `./case.setup --reset`",
        )
    else:
        toggle_build_status = False

        rebuild_components = []

        for component in case.get_values("COMP_CLASSES"):
            triggers = case.get_values(f"REBUILD_TRIGGER_{component}")

            if any([y.startswith(x) for x in triggers for y in diff.keys()]):
                toggle_build_status = True

                rebuild_components.append(component)

        if toggle_build_status:
            case.set_value("BUILD_COMPLETE", False)

        clean_targets = " ".join([x.lower() for x in rebuild_components])
        clean_cmd = f"./case.build --clean {clean_targets}"

        expect(
            False,
            f"A rebuild is required, please run: \n./case.setup --reset\n{clean_cmd}\n./case.build",
        )
