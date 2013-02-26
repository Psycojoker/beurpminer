import os
import json
import shutil
from collections import namedtuple

import argh
from jinja2 import Environment, FileSystemLoader
from highlight import HighlightExtension
from hamlish_jinja import HamlishExtension
from vodka import get_classes_from_config_file

env = Environment(extensions=[HamlishExtension, HighlightExtension], loader=FileSystemLoader('templates'))
env.hamlish_enable_div_shortcut = True
env.hamlish_mode = "indented"

def get_top_model_url(modules):
    def _(model_name):
        for module, module_content in modules.items():
            for model in module_content['models'].values():
                if model.get("_name") == model_name and not model.has_key("_inherit"):
                    return "%s/%s.html" % (module, model["class_name"])
        return ""
    return _

def get_neighbour_models(modules, current_module):
    def _(current_model):
        target = current_model.get("_inherit", current_model.get("_name"))
        if not target:
            return []
        to_return = []
        for module, module_content in modules.items():
            if module == current_module:
                continue
            for model in module_content['models'].values():
                if target in (model.get("_name"), model.get("_inherit")):
                    to_return.append((module, model))
        return to_return
    return _

def get_views_n_actions_of_model(modules, model_id):
    to_return = {"actions": [], "views": []}

    for module in modules:
        for view_id, view_content in modules[module]["xml"]["views"].items():
            if view_content["model"].replace("_", ".") in (model_id, ".".join((module, model_id)).replace("_", ".")):
                view_content.update({"id": view_id, "module": module})
                to_return["views"].append(view_content)

        for action_id, action_content in modules[module]["xml"]["actions"].items():
            if action_content["model"].replace("_", ".") in (model_id, ".".join((module, model_id)).replace("_", ".")):
                action_content.update({"id": action_id, "module": module})
                to_return["actions"].append(action_content)

    return to_return

files_to_generate = set()
FileInfos = namedtuple("FileInfos", ["file_path", "module", "file_destination_name"])

def request_file(module, file_path):
    files_to_generate.add(FileInfos(file_path=file_path, module=module, file_destination_name=format_file_name(module, file_path)))
    return "/%s/file/%s.html" % (module, format_file_name(module, file_path))

def format_file_name(module, file_name):
    result = file_name.split(module, 1)[-1][1:]
    result = result.replace(".", "_")
    result = result.replace("/", "_")
    return result

def format_method_arguments(method):
    def is_float(string):
        try:
            float(string)
            return True
        except ValueError:
            return False

    if not method["args"]:
        return "()"

    all_args = []

    if method["defaults"]:
        normal_args = method["args"][:-len(method["defaults"])]
    else:
        normal_args = method["args"]

    all_args += normal_args

    if method["defaults"]:
        default_args = method["args"][-len(method["defaults"]):]
        defaults = map(lambda x: x if not isinstance(x, basestring) or x in ("None", "True", "False") or x.isdigit() or is_float(x) else "'%s'" % x, method["defaults"])
        default_args = zip(default_args, defaults)
        default_args = map(lambda x: "%s=%s" % (x[0], x[1]), default_args)

        all_args += default_args

    if method["vararg"]:
        all_args.append("*" + method["vararg"])

    if method["kwarg"]:
        all_args.append("**" + method["kwarg"])

    return "(%s)" % ", ".join(all_args)


def get_list_of_models(modules):
    all_models = {}

    for module in modules.keys():
        for model_name, model in modules[module]["models"].items():
            # not here or is the top model
            if model.get("_name", None) is None:
                continue

            if model["_name"] not in all_models.keys() or not model.get("_inherit"):
                all_models[model["_name"]] = model.copy()
                all_models[model["_name"]]["module"] = module
    return [model for key, model in sorted(all_models.items(), key=lambda x: x[1]["_name"].lower())]


def sort_list_of_dicts(x, y):
    return sorted(x, key=lambda z: z.get(y))


def resolve_modules_dependancies(modules, modules_data, dependancies=None, verbose=False):
    if dependancies is None:
        dependancies = set()

    if not modules:
        return dependancies

    module = modules.pop()

    if module not in modules_data:
        print "WARNING: '%s' is not an available module!" % module
        return resolve_modules_dependancies(modules, modules_data, dependancies, verbose)

    for dependancy in modules_data[module]["__openerp__"].get("depends", []):
        if dependancy not in dependancies:
            if verbose:
                print "Add dependancy:", dependancy
            dependancies.add(dependancy)

        if dependancy not in modules and dependancy != module:
            modules.append(dependancy)

    dependancies.add(module)

    return resolve_modules_dependancies(modules, modules_data, dependancies, verbose)


def main(clean_dir=False, target_dir="build", cache_target=None, verbose=False, do_not_add_dependancies=False, no_source_code=False, *modules):
    if not modules:
        print "I need you to give me a list of modules for which to generate the documentation or the keyword 'all' to generate it for all the modules"
        return

    if clean_dir:
        if os.path.exists(target_dir):
            if verbose:
                print "'%s' exists, rm -rfing it" % target_dir
            shutil.rmtree(target_dir)

    if not os.path.exists(target_dir):
        shutil.copytree("foundation", target_dir)

    if cache_target is not None:
        if not os.path.exists(cache_target):
            if verbose:
                print "Building modules db, it might be quite long..."
            open("db.json", "w").write(json.dumps(get_classes_from_config_file(), indent=4))
        modules_data = json.load(open("db.json"))
    else:
        if verbose:
            print "Building modules db, it might be quite long..."
        modules_data = get_classes_from_config_file()

    if not do_not_add_dependancies:
        modules = resolve_modules_dependancies(list(modules), modules_data, verbose=verbose)

    for key in modules_data.keys():
        if key not in modules:
            del modules_data[key]

    models = get_list_of_models(modules_data)

    html = env.get_template("home.haml").render(modules=modules_data, sort_list_of_dicts=sort_list_of_dicts, models=models, model={})
    open(os.path.join(target_dir, "index.html"), "w").write(html.encode("Utf-8"))

    for module in modules_data.keys():
        if not os.path.exists(os.path.join(target_dir, "%s") % module):
            os.makedirs(os.path.join(target_dir, "%s") % module)

        for model in modules_data[module]['models']:
            html = env.get_template("entity.haml").render(modules=modules_data, model=modules_data[module]['models'][model], get_top_model_url=get_top_model_url(modules_data), get_neighbour_models=get_neighbour_models(modules_data, module), views_n_actions=get_views_n_actions_of_model(modules_data, modules_data[module]['models'][model].get('_name', '')), module=module, request_file=request_file, format_method_arguments=format_method_arguments, models=models, sort_list_of_dicts=sort_list_of_dicts, show_code=not no_source_code)
            open(os.path.join(target_dir, "%s/%s.html") % (module, model), "w").write(html.encode("Utf-8"))

    if not no_source_code:
        for file_infos in files_to_generate:
            if not os.path.exists(os.path.join(target_dir, "%s/file") % file_infos.module):
                os.makedirs(os.path.join(target_dir, "%s/file") % file_infos.module)
            html = env.get_template("source.haml").render(file_content=open(file_infos.file_path, "rb").read().decode("Utf-8"), modules=modules_data, file_path=file_infos.file_path)
            open(os.path.join(target_dir, "%s/file/%s.html") % (file_infos.module, file_infos.file_destination_name), "w").write(html.encode("Utf-8"))

if __name__ == '__main__':
    argh.dispatch_command(main)
