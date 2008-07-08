
_yap-commands () {
    local -a commands

    commands=(
	'add:add a new file to the repository'
	'branch:list, create, or delete branches'
	'cherry-pick:apply the changes in a given commit to the current branch'
	'clone:make a local copy of an existing repository'
	'commit:record changes to files as a new commit'
	'diff:show staged, unstaged, or all uncommitted changes'
	'history:alter history by dropping or amending commits'
	'init:turn a directory into a repository'
	'log:show the changelog for particular versions or files'
	'point:move the current branch to a different revision'
	'repo:list, add, or delete configured remote repositories'
	'revert:remove uncommitted changes from a file (*)'
	'rm:delete a file from the repository'
	'show:show the changes introduced by a given commit'
	'stage:stage changes in a file for commit'
	'status:show files with staged and unstaged changes'
	'switch:change the current working branch'
	'uncommit:reverse the actions of the last commit'
	'unstage:unstage changes in a file'
	'version:report the current version of yap'
    )

    _describe -t commands 'zsh command' commands && ret=0
}

_yap-unstage () {
    _arguments \
	'*:file:_files' && ret=0
}

_yap-stage () {
    _arguments \
	'*:file:_files' && ret=0
}

_yap-add () {
    _arguments \
	'*:file:_files' && ret=0
}

_yap-rm () {
    _arguments \
	'*:file:_files' && ret=0
}

_yap-branch () {
    _arguments \
	'-d[delete a branch]:local branch' \
	'*:branch' && ret=0
}

_yap () {
    if (( CURRENT == 2 )); then
	_yap-commands
    else
	shift words
	(( CURRENT-- ))
	curcontext="${curcontext%:*:*}:yap-$words[1]:"
	_call_function ret _yap-$words[1]
    fi
}

compdef _yap yap
