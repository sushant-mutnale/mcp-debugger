# MCP Server Compatibility Report

| Server | Status | Tools Found | Issues |
| :----- | :----: | :---------- | :----- |
| filesystem | ✅ PASS | read_file, read_text_file, read_media_file, read_multiple_files, write_file (+9 more) | None |
| fetch | ✅ PASS | fetch | None |
| github | ✅ PASS | create_or_update_file, search_repositories, create_repository, get_file_contents, push_files (+21 more) | None |
| memory | ✅ PASS | create_entities, create_relations, add_observations, delete_entities, delete_observations (+4 more) | None |


## filesystem

**Status:** PASS  
**Tools discovered:** read_file, read_text_file, read_media_file, read_multiple_files, write_file, edit_file, create_directory, list_directory, list_directory_with_sizes, directory_tree, move_file, search_files, get_file_info, list_allowed_directories
- `read_file`: PASS
- `list_directory`: PASS
- `get_file_info`: PASS

## fetch

**Status:** PASS  
**Tools discovered:** fetch
- `fetch`: PASS

## github

**Status:** PASS  
**Tools discovered:** create_or_update_file, search_repositories, create_repository, get_file_contents, push_files, create_issue, create_pull_request, fork_repository, create_branch, list_commits, list_issues, update_issue, add_issue_comment, search_code, search_issues, search_users, get_issue, get_pull_request, list_pull_requests, create_pull_request_review, merge_pull_request, get_pull_request_files, get_pull_request_status, update_pull_request_branch, get_pull_request_comments, get_pull_request_reviews
- `search_repositories`: PASS
- `list_commits`: PASS

## memory

**Status:** PASS  
**Tools discovered:** create_entities, create_relations, add_observations, delete_entities, delete_observations, delete_relations, read_graph, search_nodes, open_nodes
- `create_entities`: PASS